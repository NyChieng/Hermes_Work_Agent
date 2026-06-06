# Hermes Work Agent

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/NyChieng/Hermes_Work_Agent/actions/workflows/test.yml/badge.svg)](https://github.com/NyChieng/Hermes_Work_Agent/actions)

> A personal AI work assistant that thinks like a human. Tracks your tasks, calls you out when you're procrastinating, and gives honest feedback — across Web UI, Telegram, and CLI.

---

## What it does

You talk to Hermes the same way you'd update a teammate. It understands natural language, manages your task board, sends you morning/evening reports, and calls you out when you're slacking — in one of three distinct personas.

```
"API module is done"                    → marks task done, syncs to Notion
"Block the design review, waiting on X" → updates status, notes the reason
"Add a deadline of Friday for the report" → sets deadline, schedules reminder
```

---

## Features

| Category | Feature |
|----------|---------|
| **AI** | DeepSeek ReAct loop · three personas (Buddy / Drill / Boss) · emotional memory & streak tracking |
| **Tasks** | CRUD with priority, deadline, tags, notes · fuzzy name matching · soft-delete (archive) |
| **Reminders** | Morning report 09:00 · Evening report 21:00 · Hourly deadline checks (24h + 1h warnings) |
| **Weekly Report** | Auto-generated every Sunday 21:00 · persona-voiced highlights / blockers / next-week goals |
| **Pomodoro** | `/pomo` start/stop/stats · focus time logged to task notes · completion push notification |
| **OCR** | Paste or drag a photo of a whiteboard / sticky note → Gemini Flash extracts task list |
| **Notion Sync** | Bidirectional · conflict resolution by timestamp · retry with exponential backoff |
| **Web UI** | Liquid Glass design · light/dark theme · resizable panels · drag-and-drop file/image upload |
| **Telegram Bot** | Full command set · image scanning · OCR confirm flow · persona switcher with inline keyboard |
| **Web Search** | Hermes searches the internet mid-conversation (DuckDuckGo free, or Tavily for better results) |
| **Gmail** | Read unread emails, search inbox — Hermes checks your mail when relevant |
| **Export** | CSV · Markdown |
| **CI** | GitHub Actions runs `test_demo.py` on every push to `main` |

---

## Quick start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env   # then fill in the values
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | ✅ | platform.deepseek.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | ✅ | @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | ✅ | See step 3 |
| `GEMINI_API_KEY` | Optional | OCR image scanning (aistudio.google.com/app/apikey) |
| `TAVILY_API_KEY` | Optional | Better web search results (tavily.com) — DuckDuckGo used if not set |
| `GMAIL_ADDRESS` | Optional | Your Gmail address for inbox access |
| `GMAIL_APP_PASSWORD` | Optional | Gmail App Password (myaccount.google.com/apppasswords) |
| `NOTION_TOKEN` | Optional | notion.so/my-integrations → Internal Integration Token |
| `NOTION_PARENT_PAGE_ID` | Optional | 32-char ID from the target Notion page URL |
| `UI_PASSWORD` | Optional | Web UI access password (default: `changeme`) |

### 3. Get your Telegram Chat ID

```
1. Fill in TELEGRAM_BOT_TOKEN and run: python main.py
2. Send any message to your bot
3. Open: https://api.telegram.org/bot<TOKEN>/getUpdates
4. Find result[0].message.chat.id — paste it into .env
```

### 4. Test (no API calls required)

```bash
python test_demo.py
```

### 5. Run

```bash
python main.py
# Web UI → http://localhost:8000
```

On first run, Hermes creates the Notion database automatically if credentials are configured.

---

## Telegram commands

| Command | Description |
|---------|-------------|
| `/morning` | ☀️ Today's task plan |
| `/report` | 🌙 End-of-day summary |
| `/weekly` | 📋 Generate weekly report (or auto-pushes Sunday 21:00) |
| `/list` | List all tasks |
| `/mood [buddy\|drill\|boss]` | Switch persona |
| `/pomo <task name>` | Start a 25-min pomodoro |
| `/pomo stop` | Cancel current pomodoro |
| `/pomo stats` | Today / this week focus time |
| `/notion` | Notion database link |
| `/sync` | Manual Notion sync |
| `/help` | Full command reference |
| Send a photo | Scan for tasks via OCR |
| Send any text | Agent understands and acts |

---

## Three personas

Each persona has its own voice for daily messages, deadline reminders, and weekly reports.

| Mode | Character | Command |
|------|-----------|---------|
| **Buddy** 😏 | Sharp-tongued but genuinely cares. Compliments with a twist. | `/mood buddy` |
| **Drill** 🪖 | No filler. Results only. Every reply ends with an action order. | `/mood drill` |
| **Boss** 😔 | Quietly disappointed. Expects better. Uses a lot of `...` | `/mood boss` |

Personas also apply "callback rules" — if you've had 3+ bad days in a row, each persona calls it out in its own way.

---

## Web UI

Access at `http://localhost:8000` after starting.

- **Kanban board** — four columns (To Do / In Progress / Done / Blocked), each collapsible
- **Resizable panels** — drag the dividers; widths persist across sessions
- **Light / Dark theme** — toggle in the sidebar header; follows localStorage
- **Task detail panel** — inline status/priority/deadline editing, per-task agent chat
- **Image OCR** — drag an image onto the chat or click the scan button; review and confirm tasks
- **Paste to scan** — `Ctrl+V` a screenshot directly into the chat input
- **Quick actions** — hover a card to instantly mark it done
- **Search** — `/` to focus, filters all columns live
- **Export** — CSV or Markdown from the sidebar footer

---

## Scheduled jobs

| Time | Job |
|------|-----|
| Daily 09:00 | Morning report → Telegram |
| Daily 21:00 | Evening report + daily snapshot → Telegram |
| Every hour | Deadline check: push alerts for tasks due in 24h and 1h |
| Sunday 21:00 | Weekly report → Telegram |
| Every 5 min | Notion → SQLite pull |

---

## Project structure

```
hermes-work-agent/
├── main.py           # Startup orchestration
├── agent.py          # DeepSeek ReAct loop + persona switching
├── tools.py          # 6 agent tools (add / update / delete / list / query / summary)
├── db.py             # SQLite schema (6 tables) + WAL mode
├── cache.py          # 80-token summary cache
├── memory.py         # Daily snapshots · streak tracking · weekly report generator
├── prompts.py        # Three persona prompts (humanised, not rule-list style)
├── ocr.py            # Gemini Flash image → task extraction
├── notifier.py       # Morning / evening report formatting
├── notion_sync.py    # Bidirectional sync with retry logic
├── scheduler.py      # APScheduler jobs (reports · reminders · weekly · Notion poll)
├── api.py            # FastAPI: REST + SSE streaming + /api/ocr + /api/weekly
├── telegram_bot.py   # Bot: commands · OCR confirm flow · pomodoro timer
├── static/
│   ├── index.html    # Single-page app shell
│   ├── style.css     # Liquid Glass design system (light + dark)
│   └── app.js        # UI logic, resize, OCR, paste-image, theme
├── test_demo.py      # Offline tool-layer tests (no LLM calls)
├── .github/
│   └── workflows/
│       └── test.yml  # CI: runs test_demo.py on push to main
├── .env.example      # Configuration template
└── requirements.txt
```

---

## Database schema

Six SQLite tables, all created on first run:

| Table | Purpose |
|-------|---------|
| `tasks` | Main task store (name, status, priority, notes, tags, deadline, notion_id) |
| `summary_cache` | Single-row precomputed stats (keeps LLM context ~80 tokens) |
| `daily_log` | Per-day completion snapshot for memory and weekly report |
| `streak` | Good/bad streak counters + last 7-day notes |
| `agent_state` | Current mood + Notion IDs |
| `pomodoro_sessions` | Focus session records (task, start, duration, completed) |

---

## Token usage

| Content | Tokens |
|---------|--------|
| Summary cache (injected every turn) | ~80 |
| Memory block (recent history + streaks) | ~100 |
| Full task table (old approach) | ~600–2000+ |

**Saving: ~85%** vs dumping the full task list on every call.

History is trimmed by character count (≈ 1 token per 4 chars, cap at 3 000 tokens).

---

## Deploy to Railway

1. Push to GitHub
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub → select repo
3. **Variables** — add all `.env` values (never commit the `.env` file)
4. **Volumes** → Mount Path: `/app/data` (persists SQLite across deploys)
5. Deploy — access the generated URL

> SQLite lives at `/app/data/tasks.db` on Railway. Without a Volume, data resets on every deploy.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue before writing code for anything beyond a small fix.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| LLM | DeepSeek Chat (`deepseek-chat`) via OpenAI-compatible SDK |
| OCR | Google Gemini 2.0 Flash (`gemini-2.0-flash`) |
| Backend | FastAPI + Uvicorn |
| Database | SQLite (WAL mode) |
| Bot | python-telegram-bot 20.x |
| Notion | httpx + Notion REST API v1 |
| Scheduling | `schedule` library (daemon thread) |
| Frontend | Vanilla JS · CSS Liquid Glass design system |
