# Hermes Work Agent

AI 驱动的工作进度追踪系统 — 支持 CLI / Web UI / Telegram Bot 三端，
带 Notion 双向同步、OCR 图片识别、番茄钟、周报生成，以及三种性格各异的 AI 人格。

---

## 功能一览

| 功能 | 说明 | 入口 |
|------|------|------|
| 任务管理 | 增删改查，支持优先级/状态/截止日期/标签 | 三端 |
| AI 对话 | 自然语言操作任务，ReAct 推理循环 | Web UI / Telegram / CLI |
| 三种人格 | 损友 / 军训教官 / 怨念上司，可随时切换 | `/mood` |
| 情绪记忆 | 记录每日表现，连续好/差天数，翻旧账 | 自动 |
| 早晚报 | 每天 09:00 早报 + 21:00 晚报 | Telegram / `/morning` `/report` |
| **周报生成** | 每周日 21:00 自动推送，或手动触发 | Telegram `/weekly` / Web UI |
| **截止日期提醒** | 每小时检查，24h / 1h 前各推一次 | Telegram 自动 |
| **番茄钟** | 25 分钟专注计时，到点推送提醒 | Telegram `/pomo` |
| **OCR 图片识别** | 拍白板/便签/截图，自动提取任务 | Telegram 发图 / Web UI 拖拽 |
| Notion 同步 | 双向同步，冲突按时间戳解决 | 自动（每 5 分钟）|
| 导出 | 导出 CSV / Markdown | Web UI |

---

## 5 步启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置密钥

```bash
copy .env.example .env    # Windows
# cp .env.example .env   # macOS/Linux
```

填写 `.env`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | ✅ | platform.deepseek.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | ✅ | @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | ✅ | 见步骤 3 |
| `GEMINI_API_KEY` | 可选 | OCR 图片识别专用，aistudio.google.com |
| `NOTION_TOKEN` | 可选 | notion.so/my-integrations |
| `NOTION_PARENT_PAGE_ID` | 可选 | 目标页面 URL 末尾 32 位 |
| `UI_PASSWORD` | 可选 | Web UI 访问密码，默认 changeme |

### 3. 获取 Telegram Chat ID

```
1. 填好 TELEGRAM_BOT_TOKEN，运行：python main.py
2. 向你的 bot 发任意一条消息
3. 访问：https://api.telegram.org/bot<TOKEN>/getUpdates
4. 找 result[0].message.chat.id，填入 .env
```

### 4. 离线测试（可选）

```bash
python test_demo.py
```

### 5. 启动

```bash
python main.py
```

首次启动若配置了 Notion 凭据，会自动创建 Notion 数据库。

---

## 三端使用

| 端 | 访问方式 | 功能 |
|----|----------|------|
| **Web UI** | `http://localhost:8000` | 完整看板 + AI 聊天 + OCR 拖拽 + 周报 |
| **Telegram** | Bot 对话 | 消息操作 + 早晚报 + 周报 + 番茄钟 + OCR |
| **CLI** | `python agent.py` | 纯命令行对话 |

---

## Telegram 命令

| 命令 | 功能 |
|------|------|
| `/start` `/help` | 显示帮助 |
| `/morning` | ☀️ 今日任务计划 |
| `/report` | 🌙 今日收工汇报 |
| `/weekly` | 📋 **生成本周周报** |
| `/list` | 列出所有任务 |
| `/mood [friend\|drill\|boss]` | 🎭 切换人格 |
| `/notion` | Notion 数据库链接 |
| `/sync` | 手动触发 Notion 同步 |
| `/pomo <任务名>` | 🍅 开始 25 分钟番茄钟 |
| `/pomo stop` | 中断当前番茄钟 |
| `/pomo stats` | 查看今日/本周专注统计 |
| 发图片 | 📸 自动 OCR 识别任务 |
| 直接发消息 | 🤖 AI 自动理解并处理 |

---

## 三种人格

| 模式 | 风格 | 切换 |
|------|------|------|
| 😏 **损友** | 嘴很毒但真心关心，每夸一句补一刀 | `/mood friend` |
| 🪖 **军训教官** | 没废话只要结果，每句以行动指令收尾 | `/mood drill` |
| 😔 **怨念上司** | 克制的失望，省略号比语言更重 | `/mood boss` |

连续 3+ 天未完成？每种人格有专属翻旧账台词。

---

## 定时推送

| 时间 | 事件 |
|------|------|
| 每天 09:00 | ☀️ 早报（高优先级任务 + 阻塞概览）|
| 每天 21:00 | 🌙 晚报 + 记录今日快照 |
| 每小时 | ⏰ 检查截止日期，24h / 1h 前各提醒一次 |
| 每周日 21:00 | 📋 自动生成并推送周报 |
| 每 5 分钟 | 🔄 Notion → SQLite 轮询同步 |

---

## OCR 使用说明

**Telegram：** 直接向 bot 发送图片（白板、便签、截图），bot 自动识别任务列表，
回复"确认"批量创建，回复"取消"放弃。

**Web UI：** 点击输入框旁的 📸 按钮，或直接把图片拖拽到聊天区域，
识别完成后弹出确认面板，可逐条勾选后点击"全部创建"。

需要配置 `GEMINI_API_KEY`（Google AI Studio 免费申请）。

---

## 项目结构

```
hermes-work-agent/
├── main.py           # 统一入口
├── agent.py          # ReAct 循环 + 人格管理
├── tools.py          # 6 个 agent 工具（含 deadline 支持）
├── db.py             # SQLite 层（tasks / pomodoro_sessions 等6张表）
├── cache.py          # 摘要缓存
├── memory.py         # 每日快照 + streak + 周报生成
├── prompts.py        # 三种人格 prompt（人性化语气）
├── ocr.py            # Gemini Flash 图片识别
├── notifier.py       # Telegram 早晚报格式化
├── telegram_bot.py   # Telegram Bot（/pomo /weekly + OCR 确认流）
├── scheduler.py      # 定时任务（早晚报/截止提醒/周报/Notion轮询）
├── notion_sync.py    # Notion 双向同步（含重试逻辑）
├── api.py            # FastAPI（含 /api/ocr /api/weekly）
├── static/           # Web UI（Linear 风格设计）
├── test_demo.py      # 离线工具层测试
├── requirements.txt
├── .env.example
└── .github/workflows/test.yml  # CI：push main 自动跑测试
```

---

## Railway 部署

1. 推送到 GitHub
2. railway.app → New Project → Deploy from GitHub
3. Variables 页填入所有 `.env` 变量
4. Volumes → Mount Path 填 `/app/data`（持久化 SQLite）
5. 部署完成，访问生成的 URL

---

## Token 消耗

每轮对话注入约 80 tokens 摘要 + ~100 tokens 记忆块（而非完整任务列表），
比原始方案节省约 85% token 费用。历史按字符数裁剪（每4字符≈1 token，超过 3000 token 自动截断）。
