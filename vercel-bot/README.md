# Event Post Creator — Flask Webhook on Vercel

A Flask-based Telegram webhook deployable as a Vercel serverless function.
Each Telegram message triggers one function invocation — no long-running process needed.

---

## Project structure

```
├── api/
│   └── webhook.py        ← Flask app — Vercel entry point
├── main.py               ← Original Gemini pipeline (unchanged)
├── pipeline.py           ← Re-exports extract_details / generate_hook / generate_post
├── sheets.py             ← Google Sheets read/write helpers
├── formatter.py          ← Telegram Markdown formatters
├── telegram_client.py    ← Synchronous Telegram Bot API wrapper (requests)
├── set_webhook.py        ← One-time webhook registration script
├── requirements.txt      ← Flask + all dependencies
├── vercel.json           ← Vercel build + routing config
└── .env                  ← Local dev secrets (never commit)
```

---

## 1 · Local setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_BotFather

GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash          # optional, this is the default

GOOGLE_SHEET_ID=your_sheet_id_from_url

# Local dev — point to the downloaded service-account JSON file
GOOGLE_CREDS_FILE=credentials.json

# On Vercel — paste the entire JSON content as a single-line string:
# GOOGLE_CREDS_JSON={"type":"service_account","project_id":"..."}
```

---

## 2 · Google Cloud setup (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Enable **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account** → Actions → Manage keys → Add key → JSON.
4. Save the file as `credentials.json` next to `bot.py`.
5. Open your Google Sheet → Share → paste the service-account email → **Editor**.

---

## 3 · Run locally with ngrok (for testing)

```bash
# Terminal 1 — start Flask
python api/webhook.py

# Terminal 2 — expose it publicly
ngrok http 5000

# Terminal 3 — register the ngrok URL with Telegram
python set_webhook.py set https://<your-ngrok-id>.ngrok.io/api/webhook
```

Visit `http://localhost:5000/api/webhook` in your browser — you should see:
> Event Post Creator webhook is live. ✅

---

## 4 · Deploy to Vercel

### 4a · Install Vercel CLI

```bash
npm i -g vercel
vercel login
```

### 4b · Deploy

```bash
vercel --prod
```

Vercel will print your URL, e.g. `https://event-post-creator.vercel.app`

### 4c · Set environment variables

Go to **Vercel Dashboard → Project → Settings → Environment Variables**:

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `GEMINI_API_KEY` | your Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` |
| `GOOGLE_SHEET_ID` | your sheet ID |
| `GOOGLE_CREDS_JSON` | **full contents** of `credentials.json` as a string |

Convert `credentials.json` to a single-line string with:
```bash
python -c "import json; print(json.dumps(json.load(open('credentials.json'))))"
```

### 4d · Register the webhook with Telegram

```bash
python set_webhook.py set https://event-post-creator.vercel.app/api/webhook
```

Verify:
```bash
python set_webhook.py info
```

---

## 5 · How Flask integrates with Vercel

Vercel's Python runtime detects the `app` object (a Flask WSGI app) exported
from `api/webhook.py` and wraps it automatically. The `vercel.json` routes all
requests to that file. No additional WSGI server (gunicorn, uwsgi) is needed.

Flask routes used:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` or `/api/webhook` | Health check |
| `POST` | `/api/webhook` | Telegram update receiver |

---

## 6 · Notes

**Function timeout** — Vercel Hobby plan allows 10 seconds; Pro allows 60 seconds.
The full Gemini pipeline (3 sequential calls) takes ~10–25 seconds.
Upgrade to **Pro** to avoid timeouts.

**Conversation state** — stored in `/tmp/conv_state.json` on the Vercel instance.
Works for single-user / low-traffic bots. For production, replace `_load_state` /
`_save_state` in `api/webhook.py` with [Upstash Redis](https://upstash.com/) calls.

**Switch back to polling (local bot.py)**:
```bash
python set_webhook.py delete
python bot.py
```
