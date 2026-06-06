# Work Progress Agent

AI 驱动的工作进度追踪系统，支持 CLI / Web UI / Telegram Bot 三端，
带 Notion 双向同步、三种人格切换和情绪记忆。

---

## 5 步启动

### 步骤 1 — 安装依赖

```bash
pip install openai python-telegram-bot schedule httpx rich python-dotenv \
            fastapi "uvicorn[standard]"
```

### 步骤 2 — 配置密钥

```bash
copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux
```

打开 `.env`，至少填写：

| 变量 | 必填 | 获取方式 |
|------|------|----------|
| `DEEPSEEK_API_KEY` | ✅ | platform.deepseek.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | ✅ | @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | ✅ | 见步骤 3 |
| `NOTION_TOKEN` | 可选 | notion.so/my-integrations |
| `NOTION_PARENT_PAGE_ID` | 可选 | 目标页面 URL 末尾 32 位 |
| `UI_PASSWORD` | 可选 | 自定义，保护 Web UI |

### 步骤 3 — 获取 Telegram Chat ID

```
1. 先填好 TELEGRAM_BOT_TOKEN，运行：python main.py
2. 在 Telegram 向你的 bot 发一条消息（如「hello」）
3. 浏览器打开：
   https://api.telegram.org/bot<你的TOKEN>/getUpdates
4. 找 result[0].message.chat.id，填入 .env，重启
```

### 步骤 4 — 离线测试（可选，不消耗 API）

```bash
python test_demo.py
```

### 步骤 5 — 启动

```bash
python main.py
```

首次启动会自动创建 Notion 数据库（如配置了 Notion 凭据）并打印链接。

---

## 三端使用

| 端 | 启动方式 | 功能 |
|----|----------|------|
| Web UI | `python main.py` → 浏览器 `http://localhost:8000` | 完整看板 + 聊天 |
| Telegram | 同上（后台启动） | 消息更新 + 早晚报 |
| CLI | `python agent.py` | 纯命令行对话 |

---

## Telegram 命令

| 命令 | 功能 |
|------|------|
| `/start` `/help` | 帮助 |
| `/morning` | ☀️ 今日任务计划 |
| `/report` | 🌙 今日收工汇报 |
| `/list` | 📋 列出所有任务 |
| `/mood` | 🎭 切换人格（内联按钮） |
| `/notion` | 🔗 Notion 数据库链接 |
| `/sync` | 🔄 手动触发 Notion 同步 |
| 直接发消息 | 🤖 Agent 自动理解并处理 |

---

## 三种人格

| 模式 | 风格 | 切换命令 |
|------|------|----------|
| 😏 损友 | 嘴毒但真心关心，每夸一句补一刀 | `/mood friend` |
| 🪖 军训教官 | 没废话只要结果，每句以行动指令收尾 | `/mood drill` |
| 😔 怨念上司 | 克制的失望，省略号表达比语言更多的东西 | `/mood boss` |

连续 3+ 天未完成任务？每种人格都有专属"翻旧账"台词。

---

## 定时推送

| 时间 | 事件 |
|------|------|
| 每天 09:00 | 早报（高优先级任务 + 阻塞概览）|
| 每天 21:00 | 晚报（完成情况）+ 记录今日快照 |
| 每 5 分钟 | Notion → SQLite 轮询同步 |

> **注意**：Notion 同步延迟最多 5 分钟，这是轮询频率限制，不是 Bug。

---

## 项目结构

```
work-agent/
├── main.py          # 统一入口（DB init + 全服务启动）
├── agent.py         # Hermes ReAct Agent 主循环
├── tools.py         # 6 个 agent 工具（每次写操作异步推 Notion）
├── db.py            # SQLite 层（5 张表 + 状态 helpers）
├── cache.py         # 摘要缓存（控制 token 消耗）
├── memory.py        # 每日快照 + streak + 记忆块生成
├── prompts.py       # 三种人格 prompt（含翻旧账规则）
├── notifier.py      # Telegram 早报/晚报格式化
├── telegram_bot.py  # Telegram Bot（/mood 内联键盘）
├── scheduler.py     # 定时任务（报告 + Notion 轮询）
├── notion_sync.py   # Notion 双向同步（push/pull/setup）
├── api.py           # FastAPI 路由（Web UI 后端）
├── static/          # Web UI 前端
│   ├── index.html
│   ├── style.css
│   └── app.js
├── test_demo.py     # 离线工具层测试
├── tasks.db         # SQLite 数据库（自动创建）
├── .env             # 私密配置（不提交 git）
└── .env.example     # 配置模板
```

---

## Web UI

浏览器访问 `http://localhost:8000`，输入 `UI_PASSWORD` 登录。

| 功能 | 说明 |
|------|------|
| 任务看板 | 4 栏（未开始/进行中/完成/阻塞），点击卡片编辑 |
| 聊天 | SSE 流式打字机效果，与 Telegram 共享 Agent |
| 人格切换 | 点击 😏/🪖/😔 按钮，实时生效 |
| Notion 同步 | 点击 🔄 手动同步，或自动每 5 分钟轮询 |

---

## Railway 云端部署（5 步）

1. 推送到 GitHub（`git init && git push`）
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub → 选 repo
3. **Variables** 页面填入所有 `.env` 变量（不要上传 `.env` 文件）
4. **Volumes** → Mount Path 填 `/app/data`（持久化 SQLite）
5. 部署完成，访问 `https://xxx.up.railway.app`

> **Railway 免费版**：每月 $5 credits，轻量 AI Agent 完全够用。

> **数据持久化**：SQLite 文件在 `/app/data/tasks.db`，必须配置 Railway Volume
> 否则每次重新部署数据会丢失。

---

## Token 消耗

每轮对话注入约 80 tokens 摘要 + ~100 tokens 记忆块，
而非完整任务列表，比原始方案节省约 85% token 费用。
