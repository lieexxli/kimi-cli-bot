# kimi-cli-bot 产品与开发规划

**日期**: 2026-03-27
**更新**: 2026-03-28（Phase 0+1+2a 完成）
**项目**: kimi-cli-bot（kimi-cli Telegram Bot 扩展）
**参考项目**: OpenClaw、Codex、Gemini CLI、Claude Code（anthropics/claude-plugins-official/telegram）

---

## Phase 0+1 完成记录（2026-03-27）

Phase 0（适配器接口改造）和 Phase 1（体验基线）已全部完成并合并到 main。以下是实际落地情况与原设计的差异说明。

### 已完成

| 功能 | 状态 | 说明 |
|------|------|------|
| IMAdapter 接口扩展 | ✅ | 新增 `edit_message / send_chat_action / answer_callback_query / register_callback_handler` |
| TelegramAdapter 实现 | ✅ | 长轮询 + webhook 双模式，订阅 `callback_query` |
| cancel_event 提升 | ✅ | 从局部变量提升为 `self._current_cancel`，`/cancel` 可中止当前 turn |
| 流式输出 | ✅ | 第一个 TextPart 直接发消息，后续 edit 追加，500ms 节流 |
| InlineKeyboard 审批 | ✅ | 同意 / 拒绝按钮，超时自动拒绝，stale callback 友好提示 |
| 收到消息即反馈 | ✅ | typing + 👀 reaction（`ack_reaction` 可配置，留空禁用） |
| default_mode 权限控制 | ✅ | `suggest / auto / full-auto` 三级；admin 强制 full-auto |
| `auto` 模式 | ✅ | 新增，非设计内：读写文件和 shell 命令自动通过，仅工作目录外编辑需审批 |
| 输出脱敏 | ✅ | `masking.py` 独立模块，过滤 KEY/TOKEN/SECRET/JWT |
| 循环检测 | ✅ | 同一工具连续调用 ≥ N 次自动 cancel |
| Bot 管理命令 | ✅ | `/cancel /status`（删除了 `/start /help`，与 soul 层重复） |
| `[im]` 配置段 | ✅ | `Config.im: IMConfig | None`，从 kimi.toml 读取 |
| `!` Shell 直通 | ✅ | 新增，非设计内：`!cmd` 直接跑 shell，绕过 AI 和审批 |
| PowerShell 编码修复 | ✅ | 新增，非设计内：`-NonInteractive` + UTF-8 输出 |

### 与原设计的差异

- **`/start /help` 已删除**：测试发现与 soul 层已有的 `/clear /new` 重复，且 `/start` 无实际意义
- **新增 `auto` 模式**：`suggest/full-auto` 两级粒度不够，`auto` 填补中间地带
- **新增 `!` shell 直通**：让用户可以不经过 AI 直接执行命令，与 CLI 的 `!` 行为一致
- **`suggest` 模式 session state 修复**：`auto` 模式写入 `auto_approve_actions` 会持久化，切回 `suggest` 需要显式清除
- **流式输出去掉了"思考中"占位**：第一个 chunk 到达时直接发消息，避免多余的等待提示

---

## Wire 事件对齐记录（2026-03-28）

代码审查发现 Phase 0+1 的 `case _: pass` 遗漏了若干 Wire 事件，导致 IM 与 CLI 体验不对齐。已修复：

| Wire 事件 | 之前 | 修复后 |
|-----------|------|--------|
| `CompactionEnd` | 静默丢弃 | 发送 "📦 历史对话已自动压缩" 通知 |
| `PlanDisplay` | 静默丢弃（`/plan` 命令完全无效） | 发送计划内容到 IM |
| `Notification` | 静默丢弃（系统通知丢失） | 按 severity 前缀发送给用户 |
| `StatusUpdate` | 静默丢弃 | 累积存储在 `_last_status`，`/status` 命令可读取 |
| `/status` 命令 | 仅显示版本/会话数/模型 | 新增上下文 token 用量和 plan 模式状态 |

**未处理（设计决策）**：

| Wire 事件 | 理由 |
|-----------|------|
| `SteerInput` | 需要 mid-turn 输入注入架构，IM 消息队列不支持；低优先级 |
| `MCPLoadingBegin/End` | 瞬态状态，在手机消息流里发送会产生噪音 |
| `CompactionBegin` | 只发 End 通知已够，Begin 是多余的中间状态 |
| `SubagentEvent` | 子 agent 的输出会通过主 agent 的 TextPart 汇总，不需要单独展示 |



---

## 一、现状摘要

kimi-cli-bot 在 MoonshotAI/kimi-cli 基础上添加了 Telegram Bot 适配层。核心实现约 800 行，单用户场景已能跑通。

**已有能力**（kimi-cli 原生，无需重新实现）：
- 会话持久化：`context.json` 每用户独立，重启自动续接
- 审批机制：`soul/approval.py` 完整实现，IM 模式只是强制设了 `yolo=True`
- 上下文压缩：`soul/compaction.py` 已有，超阈值自动触发
- 后台任务：`background/manager.py` 完整实现
- 多模型支持：`kimi.toml` 可配置任意 OpenAI 兼容模型
- Soul 层斜杠命令：`/clear /yolo /compact /plan /export` 用户在 Telegram 直接发消息即可触发

**真正缺失的**：

| 缺失 | 根因 |
|------|------|
| 无流式输出 | `session.py:214` 只在 `TurnEnd` 时一次性发送，`IMAdapter` 只有 `send_message()` |
| 审批交互原始 | 无 InlineKeyboard，`allowed_updates` 未订阅 `callback_query` |
| 无管理命令 | `/cancel` 需要把 `cancel_event`（当前局部变量 `session.py:210`）提升到 session 状态 |
| 执行权限全开 | IM 模式强制 `yolo=True` |
| 无速率限制 | 任意用户可无限发消息 |
| 无循环检测 | Agent 陷入循环会在 Telegram 里刷屏 |
| 无输出脱敏 | Shell 输出可能把 API Key、密码直接发给用户（当前最大泄露面） |
| Prompt Injection 无防护 | Agent 可被诱导执行敏感操作，保护点应在能力层而非文本过滤 |
| 会话文件无限增长 | 内存中 `IMSession` 无 idle 清理，磁盘无上限 |

**前置瓶颈**：`IMAdapter` 抽象层当前只有 `send_message()`（`ui/im/__init__.py:58`），Telegram adapter 的 polling 只订阅了 `message`（`telegram.py:131`）。流式输出、内联按钮、typing indicator 都依赖扩展这个接口，**必须先做接口改造**，其余 P0 项才能落地。

---

## 二、目标与边界

**目标**：一个人或小圈子（<10 人）共用一个 Bot，在手机上随时触达完整 AI Agent 能力。

**架构说明**：Claude Code 的 Telegram 插件是 MCP Server 模式；kimi-cli-bot 是嵌入式适配层，架构不同，借鉴其安全设计而非架构。

**不做**：
- 多租户 SaaS、Web 控制台
- TOML 策略引擎（企业级，YAGNI）
- 配对机制（常驻服务无人守终端；静态白名单适合此部署模型）
- Docker 沙箱（个人工具不值运维成本）
- 工具执行状态播报（Telegram 消息流里每条工具调用发一条消息是骚扰）
- A2A/跨 Bot 协议（无实际用例）
- 多通道支持（聚焦 Telegram）

---

## 三、优先级矩阵

| 优先级 | 功能 | 说明 | 来源 |
|--------|------|------|------|
| **P0** | **适配器接口改造** | 扩展 `IMAdapter`；Telegram 侧加 `edit_message / send_chat_action / callback_query`；其余 P0 依赖此项 | 前置 |
| **P0** | 流式输出 | `edit_message` 实时追加，"⌛ 思考中..."占位 | OpenClaw |
| **P0** | 内联按钮审批 | InlineKeyboard 替代文本判断 | OpenClaw |
| **P0** | 收到消息即反馈 | typing 状态 + 👀 reaction | Claude Code |
| **P0** | 默认关闭 yolo | `[im] default_mode = "suggest"`，管理员默认 full-auto | Codex |
| **P0** | 输出脱敏 | 正则过滤 `*_KEY= *_TOKEN=` 等，当前最大泄露面 | Gemini CLI |
| **P0** | 循环检测 | 同一工具连续调用 N 次自动停止 | Gemini CLI |
| **P0** | 基础管理命令 | `/start /help /status`（Bot 层）；`/cancel` 需提升 cancel_event | OpenClaw |
| **P1** | 速率限制 | 每用户滑动窗口 RPM | OpenClaw |
| **P1** | Prompt Injection 防护 | capability guard：敏感能力（改白名单、读配置）不暴露给 Telegram 触发的 Agent | Claude Code |
| **P1** | 压缩感知通知 | 压缩触发时发系统消息 | Gemini CLI |
| **P1** | 分页优化 | 按段落边界分割；首页 reply 到原消息形成线程 | Claude Code |
| **P1** | 安全文档 | README：白名单用户 = 服务器 Shell 权限 | — |
| **P2** | 文件发送保护 | 等文件发送接口实现后再加；保护 kimi.toml 等路径 | Claude Code |
| **P2** | 会话超时清理 | 内存 30 分钟 idle 清理；磁盘可配保留天数 | OpenClaw |
| **P2** | /status token 展示 | 估算上下文使用率、对话轮数 | Gemini CLI |
| **P2** | 每用户 PERSONA.md | `sessions/<chat_id>/PERSONA.md` 注入 system prompt | Codex |
| **P2** | 文件附件支持 | PDF、代码文件，依赖 P2 文件发送接口 | — |
| **P3** | 多模型文档 + /model 命令 | kimi-cli 已支持多模型，补文档 + 命令暴露 | — |
| **P3** | 预设 Skills | 利用现有 BackgroundTaskManager，定时通知/监控 | Codex |

---

## 四、开发规划

### Phase 0：适配器接口改造（前置，~3 天）

**所有 Phase 1 的 P0 项都依赖这一步。不做完此 Phase 就开始 Phase 1 会边做边返工。**

#### 0.1 扩展 IMAdapter 抽象层

`src/kimi_cli/ui/im/__init__.py` 新增三个抽象方法：

```python
@abstractmethod
async def edit_message(self, chat_id: str, message_id: int, text: str) -> None:
    """Edit a previously sent message (for streaming)."""

@abstractmethod
async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
    """Send a chat action (e.g. typing indicator)."""

@abstractmethod
async def answer_callback_query(self, callback_query_id: str) -> None:
    """Acknowledge an inline keyboard button press."""
```

同时在 `IMAdapter` 上定义 callback 注册接口，供 session 层注册审批按钮的回调处理器。

#### 0.2 Telegram adapter 实现新接口

`src/kimi_cli/ui/im/adapters/telegram.py`：

- 实现 `edit_message / send_chat_action / answer_callback_query`
- 将 `allowed_updates=["message"]` 改为 `["message", "callback_query"]`
- 注册 `callback_query` handler，路由到 session 层的回调处理

#### 0.3 /cancel 的 cancel_event 提升

`src/kimi_cli/ui/im/session.py`：

- 将 `cancel_event = asyncio.Event()`（当前 `_run_turn` 局部变量，第 210 行）提升为 `IMSession` 成员变量 `self._current_cancel: asyncio.Event | None`
- 明确语义：`/cancel` 触发时 set 当前 event；若无运行中任务则回复"无正在运行的任务"；排队中的消息不受影响（只取消当前 turn）

---

### Phase 1：体验基线（~1 周，依赖 Phase 0）

#### 1.1 流式输出

- 收到消息后先发一条"⌛ 思考中..."占位消息，记录 `message_id`
- Agent 每产出一个 `TextPart` 时调用 `edit_message` 追加到占位消息
- 节流：每 500ms 最多 edit 一次（Telegram ~30 次/秒限制）
- 超过 4096 字符时起新消息，旧消息末尾加 `▶`，新消息标注页码
- 文件：`src/kimi_cli/ui/im/session.py`（改 `_run_turn` 输出逻辑）

#### 1.2 内联按钮审批

- `ApprovalRequest` 触发时调用 `send_message` 发带 InlineKeyboard 的消息（`✅ 同意` / `❌ 拒绝`）
- `callback_query` 收到时：answer（消除 loading 状态）→ edit 掉 reply_markup（防重复点击）→ 解除 session 的审批等待
- 拒绝时：消息变为"❌ 已拒绝，请说明原因"，下一条普通消息作为拒绝理由
- 文件：`src/kimi_cli/ui/im/session.py`、`adapters/telegram.py`

#### 1.3 收到消息即反馈

两行改动，放到消息入口最前面：

```python
await adapter.send_chat_action(chat_id, "typing")
await bot.set_message_reaction(chat_id, message_id, [ReactionTypeEmoji(emoji="👀")])
```

配置：`[im] ack_reaction = "👀"`（空字符串禁用）

#### 1.4 默认关闭 yolo

```toml
[im]
default_mode = "suggest"   # suggest | full-auto
admin_chat_ids = []        # 管理员默认 full-auto，且绕过速率限制
```

修改 `_get_kimi()` 根据 `chat_id` 是否在 `admin_chat_ids` 及 `default_mode` 设置 `yolo`。

管理员**不绕过**的保护：循环检测（是 bug 不是权限问题）、输出脱敏（Telegram 非端对端加密）。

#### 1.5 输出脱敏（当前最大泄露面，前移到 P0）

在 session 层输出管道加过滤，作用于所有发往 Telegram 的文本：

```python
SENSITIVE_PATTERNS = [
    r'[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|PWD)\s*=\s*\S+',
    r'sk-[a-zA-Z0-9]{32,}',
    r'eyJ[a-zA-Z0-9+/=]{20,}',  # JWT
]

def mask_output(text: str) -> str:
    for p in SENSITIVE_PATTERNS:
        text = re.sub(p, lambda m: m.group(0).split('=')[0] + '=[REDACTED]', text)
    return text
```

配置：`[im.security] output_masking = true`（默认开启）

#### 1.6 循环检测

- `IMSession` 维护 `_tool_call_counter: dict[str, int]`，每次工具调用时记录
- 同一工具连续调用超过阈值（默认 5）时：set cancel_event + 发送告警消息
- turn 结束时清零计数器
- 配置：`[im] loop_detection_threshold = 5`
- 文件：`src/kimi_cli/ui/im/session.py`（不另建文件，逻辑简单）

#### 1.7 基础管理命令

新增 `src/kimi_cli/ui/im/commands.py`，注册 Telegram Bot 层命令（与 soul 层斜杠命令不同，操作 IMSession/IMServer）：

| 命令 | 说明 | 权限 |
|------|------|------|
| `/start` | 欢迎消息 + 功能说明（含 soul 层已有命令列表） | 所有人 |
| `/help` | 功能帮助 | 所有人 |
| `/cancel` | 中止当前 turn，依赖 Phase 0.3 的 cancel_event 提升 | 当前用户 |
| `/status` | 活跃会话数、版本、当前模型 | 管理员 |

soul 层的 `/clear /yolo /compact` 用户直接发消息触发，无需重复实现。

---

### Phase 2：安全加固（~1 周）

#### 2.1 速率限制

```python
# src/kimi_cli/ui/im/rate_limiter.py
class RateLimiter:
    def __init__(self, rpm: int):
        self._rpm = rpm
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, chat_id: str) -> bool:
        now = time.monotonic()
        dq = self._timestamps[chat_id]
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= self._rpm:
            return False
        dq.append(now)
        return True
```

超限时回复友好提示，管理员豁免。配置：`[im.rate_limit] rpm = 20`

#### 2.2 Prompt Injection 防护（capability guard，非文本过滤）

**设计原则**：保护点在能力层，不是文本分类层。通过关键词匹配消息内容来决策会误伤正常讨论，且容易被绕过。

正确做法：**敏感能力压根不向 Telegram 触发的 Agent 暴露**：

- `kimi.toml` 及其所在目录加入 kimi-cli 的文件操作黑名单（`KIMI_DENY_PATHS` 环境变量或配置项），Agent 无法读取
- 白名单修改（`im_allow`）只能通过重启 Bot + 修改配置文件实现，不存在运行时修改接口
- `/yolo` 等 soul 层命令保持可用（它们改变的是 session 内状态，不是持久化配置）

#### 2.3 压缩感知通知

监听 kimi-cli 压缩事件（在 `_run_turn` 中检测 `StatusUpdate` 中上下文使用率骤降），触发时发送：

```
📦 历史对话已自动压缩（保留最近内容）
如需完整上下文请用 /clear 开启新对话
```

#### 2.4 分页优化

- 超 4096 字符时优先在 `\n\n` 处分割（`chunkMode=newline`），而非硬截断
- 第一页 reply 到原始消息形成线程（`replyToMode=first`），后续页独立发送
- 页码标注：`(1/3)`

#### 2.5 安全文档

README 增加"安全说明"：

```
⚠️ 重要：full-auto 模式下，白名单内的 Telegram 用户
等同于拥有运行本 Bot 的服务器 Shell 执行权限。

建议：
1. kimi.toml 设置 default_mode = "suggest"
2. 严格控制 im_allow 白名单
3. 不要以 root 运行 Bot
4. work-dir 设置 chmod 700
```

---

### Phase 3：会话治理（~1 周）

#### 3.1 内存清理

`IMSession` 30 分钟无活动后从 `IMServer._sessions` 移除，重新收到消息时从文件重载。

#### 3.2 磁盘清理

- 可配置保留天数（默认 30 天）
- `context.json` 超 10MB 触发 kimi-cli 原有 compaction
- `asyncio.Queue()` 设容量上限（默认 100），超限回复"繁忙，请稍后重试"

---

### Phase 4：体验增强（按需）

#### 4.1 /status token 展示

```
📊 会话状态
├─ 模型：gemini/gemini-2.5-flash-lite
├─ 上下文：约 12,400 token（~12%）
├─ 对话轮数：23 轮
└─ 上次压缩：2 小时前
```

#### 4.2 每用户 PERSONA.md

`sessions/<chat_id>/PERSONA.md` 在会话初始化时注入 system prompt。

#### 4.3 文件附件 + 文件发送保护

先实现文件附件接收（PDF/TXT/代码，< 20MB），同步加入 `assertSendable()` 保护：拒绝发送 kimi.toml、session 目录、`.env` 等路径下的文件。两个功能同一个 Phase 实现，避免先开洞后堵。

#### 4.4 Markdown 格式化

代码块用 `parse_mode=MarkdownV2`，Shell 输出等宽字体显示。

---

## 五、技术决策说明

**IMAdapter 扩展策略**：新增方法而非另建 Telegram 特化抽象，保持接口通用性；若未来需要支持其他 IM，已有方法可复用，Telegram 特有能力（reaction 等）作为可选接口。

**Prompt Injection 防护不用文本分类**：关键词匹配既误伤又可绕过。正确边界是：能力本身不暴露，而不是对输入做分类判断。

**`default_mode` 是破坏性变更**：需在 CHANGELOG 和升级说明中明确，给出迁移配置（`default_mode = "full-auto"` 恢复旧行为）。

**文件发送保护推迟到 P2**：当前适配器无文件发送接口，不存在这个漏洞面；等接口建立时同步加保护，不提前加无意义的空保护。

---

## 六、验收指标

| 指标 | 当前基线 | Phase 1 目标 | 验收方式 |
|------|---------|-------------|---------|
| 首字反馈时间 | 等待全部输出完成（数秒~数十秒） | ≤ 1s 出现占位消息 | 发消息计时 |
| 审批完成率 | 需要猜测文本格式，易失败 | 按钮点击 1 次完成，0 歧义 | 手动测试 10 次审批 |
| 输出脱敏覆盖 | 0% | `KEY=/TOKEN=/SECRET=` 格式全部 `[REDACTED]` | 单测：构造包含各类密钥格式的输出，断言无明文 |
| 单 chat 内存上界 | 无上界 | Phase 3 后：idle 30 分钟自动释放 | 压测：模拟 idle 后检查 `_sessions` |
| 单 chat 磁盘上界 | 无上界 | Phase 3 后：`context.json` ≤ 10MB 触发压缩 | 写入超量 context 后检查压缩触发 |
