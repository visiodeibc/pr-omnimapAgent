# 🗺️ OmniMap Agent

A production-ready Telegram bot built with **Python (FastAPI)**, **python-telegram-bot**, and **Supabase**, designed to run on **Google Cloud Run** or any container platform with webhook support and a unified background worker.

Objective: Extract, analyze, and enrich map data from user-provided content. Start with Instagram Reels → likely places with Google Maps links; expand to more sources and propose map update suggestions.

## ✨ Features

- 🚀 **Cloud-ready**: Deploy to Google Cloud Run, Docker, or any container platform
- 🐍 **Pure Python**: FastAPI + python-telegram-bot for webhook handling
- 🔄 **Unified worker**: Single background worker handles all job types
- 🗄️ **Supabase integration**: Persistent storage and background job processing
- 🔒 **Secure**: Webhook secret validation and environment variable validation
- 🎯 **Modern stack**: FastAPI, python-telegram-bot, httpx
- 🧭 **Map extraction (WIP)**: From content → candidate places with links

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd pr-omnimapAgent/python/agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Setup

```bash
# Create .env file in python/agent/
cd python/agent
nano .env
```

Required environment variables:

- `BOT_TOKEN`: Get from [@BotFather](https://t.me/BotFather)
- `WEBHOOK_SECRET`: Generate a long random string
- `PUBLIC_URL`: Your deployed service URL (e.g., https://your-service.run.app)
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_SERVICE_ROLE`: Your Supabase service role key (required)

Optional:

- `PYTHON_WORKER_POLL_INTERVAL`: Job polling interval in seconds (default: 5)
- `PYTHON_WORKER_ENABLED`: Enable/disable background worker (default: true)

### 3. Database Setup (Prisma)

This project uses Prisma to manage the Supabase (Postgres) schema. No manual SQL is required.

1. Add database env vars to `.env.local` (see `prisma/.env.example` for reference):

```env
DATABASE_URL="postgresql://..."   # Supabase Pooler URL (pgBouncer)
DIRECT_URL="postgresql://..."     # Supabase Direct URL (5432)
```

2. Generate the Prisma client and apply migrations:

```bash
pnpm prisma:generate
pnpm prisma:deploy   # applies the checked-in migrations
```

That's it. The checked-in Prisma schema defines the `jobs` table used by the bot and worker.

### 4. Development Mode

#### Local Webhook Mode with Tunnel

```bash
# Terminal 1: Start FastAPI server
cd python/agent
uvicorn main:app --reload --host 0.0.0.0 --port 8080

# Terminal 2: Expose localhost with ngrok
ngrok http 8080

# Terminal 3: Set webhook with ngrok URL
cd python/agent
PUBLIC_URL=https://your-ngrok-url.ngrok.io python set_webhook.py
```

### 5. Production Deployment

#### Deploy to Google Cloud Run

```bash
# Deploy the Python agent
cd python/agent
gcloud run deploy omnimap-python-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars BOT_TOKEN=xxx,WEBHOOK_SECRET=yyy,SUPABASE_URL=zzz,SUPABASE_SERVICE_ROLE=aaa,PUBLIC_URL=https://your-service.run.app

# Set webhook
python set_webhook.py
```

#### Deploy with Docker

```bash
# Build image
cd python/agent
docker build -t omnimap-agent .

# Run container
docker run -p 8080:8080 \
  -e BOT_TOKEN=xxx \
  -e WEBHOOK_SECRET=yyy \
  -e SUPABASE_URL=zzz \
  -e SUPABASE_SERVICE_ROLE=aaa \
  -e PUBLIC_URL=https://your-domain.com \
  omnimap-agent
```

### 6. Background Worker

The background worker is integrated into the FastAPI application and starts automatically when `PYTHON_WORKER_ENABLED=true` (default). It processes all job types:

- `python_hello` - Hello world demo
- `notify_user` - Send messages to Telegram users
- `echo_job` - Echo test jobs

The worker polls Supabase every `PYTHON_WORKER_POLL_INTERVAL` seconds (default: 5) for queued jobs.

### 7. Reels → Maps (WIP)

- Telegram UI: The "🎬 Reels → Maps" button exists and replies with a placeholder.
- Extraction core: A plugin-based orchestrator is scaffolded to support Instagram/TikTok/text inputs.
- Worker: A generic `extract` job is available that routes inputs through the orchestrator and replies with a summary.

### 8. Prisma (Schema Management)

We use Prisma to manage the Postgres (Supabase) schema. Set `DATABASE_URL` in `.env.local` to your Supabase connection string.

Commands:

```bash
# Generate client
pnpm prisma:generate

# Create and apply a migration based on prisma/schema.prisma
pnpm prisma:migrate --name init

# Deploy pending migrations (CI/production)
pnpm prisma:deploy
```

Notes:

- The Prisma schema defines `jobs` to match this project.
- This repo includes an initial migration; use `pnpm prisma:deploy` to apply it in CI/prod.
- Ensure `DATABASE_URL` uses the pooled (non-readonly) connection string and set `DIRECT_URL` for migrations.

#### Prisma datasource configuration

The schema is configured to use a pooled URL for runtime and a direct URL for migrations:

- `DATABASE_URL`: Supabase Pooler (pgBouncer) URL, e.g. `...@<POOLER_HOST>:6543/postgres?pgbouncer=true&sslmode=require`
- `DIRECT_URL`: Supabase Direct URL, e.g. `...@db.<PROJECT_REF>.supabase.co:5432/postgres?sslmode=require`

`prisma migrate deploy` uses `DIRECT_URL` under the hood. Ensure outbound access to port 5432 is allowed on your network.

#### Troubleshooting P1001 (can't reach database server)

- Verify `DIRECT_URL` is correct and includes `sslmode=require`.
- Check your network/VPN/firewall allows outbound `5432` to `db.<PROJECT_REF>.supabase.co`.
- Test connectivity: `nc -vz db.<PROJECT_REF>.supabase.co 5432` (or `openssl s_client -connect db.<PROJECT_REF>.supabase.co:5432`)
- If 5432 is blocked, you can temporarily run migrations through the Pooler:
  - Set `DATABASE_URL` to your Pooler URL in `prisma/.env`.
  - Run: `pnpm prisma:deploy:pooler` (this overrides `DIRECT_URL` with the Pooler for the deploy run).
  - After success, revert to the direct URL for future migrations.

## 🏗️ Project Structure

```
python/agent/
├── main.py                 # FastAPI app + webhook endpoint
├── bot_handlers.py         # Telegram command handlers
├── worker.py               # Unified job processor
├── supabase_client.py      # Supabase REST API client
├── settings.py             # Environment configuration
├── set_webhook.py          # Webhook setup script
├── requirements.txt        # Python dependencies
└── Dockerfile              # Container image

prisma/
└── schema.prisma           # Prisma schema for Postgres (Supabase)
```

## 🧩 Architecture

![System Architecture Diagram](public/diagram.png)

The OmniMap Agent follows a modular architecture:

```
┌─────────────────────────────────────────┐
│      Python FastAPI Agent               │
│  ┌────────────────────────────────────┐ │
│  │  Webhook: /api/tg                  │ │
│  │  Bot: bot_handlers.py (PTB)        │ │
│  │  Worker: worker.py (unified)       │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
                  │
                  ▼
          ┌──────────────┐
          │   Supabase   │
          │  (jobs table)│
          └──────────────┘
```

## 🤖 Bot Commands

- `/start` - Welcome message with interactive buttons
- `/help` - List available commands
- `/hello` - Test the Python worker pipeline (demo)

## 🔧 Scripts

| Script                      | Description                                |
| --------------------------- | ------------------------------------------ |
| `pnpm prisma:generate`      | Generate Prisma client                     |
| `pnpm prisma:migrate`       | Create/apply a migration from schema       |
| `pnpm prisma:deploy`        | Apply pending migrations (CI/prod)         |
| `pnpm prisma:deploy:pooler` | Migrate via pooled DATABASE_URL (fallback) |

## 🔐 Security Notes

- ✅ Webhook endpoints validate secret tokens
- ✅ Environment variables are validated
- ✅ Never commit `.env*` files to version control
- ⚠️ Keep webhook handlers fast (< 1 second response time)
- ⚠️ Use background jobs for heavy processing

## 🧭 Roadmap

Phase 1 — Extraction

- [x] Instagram Reels/Post → candidate places with Google Maps links
- [ ] Accept other inputs (plain text, websites) to extract places
- [ ] Export results as JSON/CSV for downstream use

Phase 2 — Enrichment

- [ ] Enrich places via Google Places/OpenStreetMap details
- [ ] De-duplicate/merge candidates; confidence scoring
- [ ] Region hints and language handling

Phase 3 — Update Suggestions

- [ ] Generate suggested map updates (e.g., OSM edits) for review
- [ ] Human-in-the-loop review flows inside Telegram
- [ ] Track applied/approved suggestions

Phase 4 — Usage & Billing (optional)

- [ ] Usage logging and quotas
- [ ] Team sharing / collaboration
- [ ] Billing integration if needed

## 🐛 Troubleshooting

### Bot not responding

- Check `BOT_TOKEN` is correct
- Verify network connectivity
- Check Telegram API status

### Webhook issues

- Ensure `WEBHOOK_SECRET` matches
- Verify `PUBLIC_URL` is accessible
- Check Cloud Run logs

### Database errors

- Verify Supabase credentials
- Check table permissions
- Ensure tables exist

### Feature placeholders

- Reels → Maps: currently returns a placeholder. No action required.

## 📝 License

MIT License - see LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

Built with ❤️ using FastAPI, python-telegram-bot, and Supabase
