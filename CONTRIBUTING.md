# Contributing to Hermes

Thanks for considering a contribution. Hermes is a personal assistant that runs across Web, Telegram, and CLI — any improvement that makes the experience feel more human and useful is welcome.

## Before you start

Open an issue first for anything beyond a typo fix. It saves both of us time if we agree on direction before code gets written.

## Setup

```bash
git clone https://github.com/NyChieng/Hermes_Work_Agent
cd Hermes_Work_Agent
pip install -r requirements.txt
cp .env.example .env
# fill in at minimum: DEEPSEEK_API_KEY
python test_demo.py   # should pass with no API calls
```

## Guidelines

**Code style**
- Python 3.11+ — use `str | None` not `Optional[str]`
- No new dependencies unless genuinely necessary
- New DB columns: add migration in `init_db()` using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern
- New Telegram commands: register in `run_telegram_bot()` and add to `_HELP_TEXT`

**What counts as a good PR**
- Bug fixes with a clear description of root cause
- Features that align with the "personal assistant" angle — things that make Hermes feel more like a thinking companion, less like a CRUD app
- UI improvements that stay within the existing Liquid Glass design system (no new CSS frameworks)
- Performance improvements (especially anything that reduces the per-message latency)

**What to avoid**
- Don't change persona tone/content without a strong reason — the personalities are intentional
- Don't add required environment variables without a graceful fallback
- Don't break the offline test (`test_demo.py` must still pass)

## Testing

```bash
python test_demo.py       # tool layer — no LLM calls, runs in seconds
python main.py            # full integration test — needs real .env keys
```

There's no pytest suite yet. If you add one, that's a welcome contribution on its own.

## Submitting

1. Fork → branch off `main`
2. Keep PRs focused — one thing per PR
3. Describe the problem you're solving, not just what you changed
4. The CI will run `test_demo.py` automatically

## Questions

Open a GitHub Discussion or drop a comment on a relevant issue.
