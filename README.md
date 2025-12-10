# 🗺️ OmniMap Agent

A multi-platform messaging bot built with **Python (FastAPI)** and **Supabase**, designed to extract places from content (Instagram Reels, TikTok, etc.) and turn them into useful map links.

## ✨ Features

- 🚀 **Cloud-ready**: Deploy to Google Cloud Run, Docker, or any container platform
- 🐍 **Pure Python**: FastAPI + python-telegram-bot for webhook handling
- 🔄 **Unified worker**: Single background worker handles all job types
- 🗄️ **Supabase integration**: Persistent storage and background job processing
- 🔒 **Secure**: Webhook secret validation and environment variable validation
- 🌐 **Multi-platform**: Telegram (full), Instagram (ready), TikTok (scaffold)

## 📁 Project Structure

```
omnimap-agent/
├── adapters/              # Platform messaging adapters
│   ├── base.py            # Abstract interfaces & types
│   ├── registry.py        # Adapter management
│   ├── telegram.py        # Telegram adapter (full)
│   ├── instagram.py       # Instagram adapter (ready)
│   └── tiktok.py          # TikTok adapter (scaffold)
├── prisma/                # Database schema & migrations
│   ├── schema.prisma
│   └── migrations/
├── main.py                # FastAPI app + webhook endpoints
├── worker.py              # Unified job processor
├── bot_handlers.py        # Telegram command handlers
├── settings.py            # Multi-platform configuration
├── supabase_client.py     # Supabase REST client
├── set_webhook.py         # Webhook setup script
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container build
└── README.md              # This file
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd omnimap-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Setup

Create a `.env` file:

```bash
# Required
BOT_TOKEN=your_telegram_bot_token
WEBHOOK_SECRET=your_random_webhook_secret
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE=your_service_role_key
PUBLIC_URL=https://your-domain.com

# Optional
PYTHON_WORKER_POLL_INTERVAL=5
PYTHON_WORKER_ENABLED=true

# Instagram (optional)
INSTAGRAM_ACCESS_TOKEN=your_page_access_token
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_ACCOUNT_ID=your_account_id

# TikTok (optional)
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
```

### 3. Database Setup (Prisma)

```bash
# Add DATABASE_URL and DIRECT_URL to prisma/.env
pnpm prisma:generate
pnpm prisma:deploy
```

### 4. Development

```bash
# Terminal 1: Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8080

# Terminal 2: Expose with ngrok
ngrok http 8080

# Terminal 3: Set webhook
PUBLIC_URL=https://your-ngrok-url.ngrok.io python set_webhook.py
```

## 🐳 Deployment

### Google Cloud Run

```bash
gcloud run deploy omnimap-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars BOT_TOKEN=xxx,WEBHOOK_SECRET=yyy,SUPABASE_URL=zzz,SUPABASE_SERVICE_ROLE=aaa,PUBLIC_URL=https://your-service.run.app

# Set webhook after deploy
python set_webhook.py
```

### Docker

```bash
docker build -t omnimap-agent .
docker run -p 8080:8080 \
  -e BOT_TOKEN=xxx \
  -e WEBHOOK_SECRET=yyy \
  -e SUPABASE_URL=zzz \
  -e SUPABASE_SERVICE_ROLE=aaa \
  -e PUBLIC_URL=https://your-domain.com \
  omnimap-agent
```

## 🔌 API Endpoints

| Endpoint         | Method | Description                    |
| ---------------- | ------ | ------------------------------ |
| `/health`        | GET    | Health check                   |
| `/api/tg`        | POST   | Telegram webhook               |
| `/api/instagram` | GET    | Instagram webhook verification |
| `/api/instagram` | POST   | Instagram webhook events       |
| `/api/tiktok`    | GET    | TikTok webhook verification    |
| `/api/tiktok`    | POST   | TikTok webhook events          |

## 🤖 Bot Commands

- `/start` - Welcome message with interactive buttons
- `/help` - List available commands
- `/hello` - Test the Python worker pipeline

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python FastAPI Agent                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Webhooks:                                                 │   │
│  │   POST /api/tg       - Telegram                          │   │
│  │   POST /api/instagram - Instagram Messenger              │   │
│  │   POST /api/tiktok   - TikTok                            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Adapter Registry                                         │   │
│  │   - Platform-agnostic message routing                    │   │
│  │   - Unified IncomingMessage/OutgoingMessage format       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Unified Worker                                           │   │
│  │   - Processes jobs from Supabase queue                   │   │
│  │   - Routes responses to correct platform                 │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                      ┌──────────────┐
                      │   Supabase   │
                      │  (jobs table)│
                      └──────────────┘
```

## 🧭 Roadmap

### Phase 1 — Extraction

- [x] Instagram Reels/Post → candidate places with Google Maps links
- [ ] Accept other inputs (plain text, websites)
- [ ] Export results as JSON/CSV

### Phase 2 — Enrichment

- [ ] Enrich places via Google Places/OpenStreetMap
- [ ] De-duplicate/merge candidates
- [ ] Region hints and language handling

### Phase 3 — Update Suggestions

- [ ] Generate suggested map updates for review
- [ ] Human-in-the-loop review in Telegram
- [ ] Track applied suggestions

## 🔐 Security Notes

- ✅ Webhook endpoints validate secret tokens
- ✅ Environment variables are validated on startup
- ⚠️ Never commit `.env` files
- ⚠️ Keep webhook handlers fast (< 1 second)

## 📝 License

MIT License - see LICENSE file for details.

---

Built with ❤️ using FastAPI, python-telegram-bot, and Supabase
