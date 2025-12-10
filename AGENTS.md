# Repository Guidelines

## Project Structure & Module Organization

- `python/agent/`: Python FastAPI application (main codebase)
  - `main.py`: FastAPI app with webhook endpoint (`POST /api/tg`) and health check
  - `bot_handlers.py`: Telegram command handlers (python-telegram-bot)
  - `worker.py`: Unified background job processor
  - `supabase_client.py`: Supabase REST API client
  - `settings.py`: Environment configuration with Pydantic
  - `set_webhook.py`: Webhook setup script
- `prisma/`: Database schema and migrations
  - `schema.prisma`: Prisma schema for Supabase (Postgres)
  - `migrations/`: SQL migrations

## Build, Test, and Development Commands

### Python Agent

```bash
# Install dependencies
cd python/agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start development server
uvicorn main:app --reload --host 0.0.0.0 --port 8080

# Set webhook (after exposing via ngrok)
PUBLIC_URL=https://your-url.ngrok.io python set_webhook.py
```

### Prisma (Database Migrations)

- `pnpm prisma:generate`: Generate Prisma client
- `pnpm prisma:migrate`: Create/apply a migration from schema
- `pnpm prisma:deploy`: Apply pending migrations (CI/prod)

## Coding Style & Naming Conventions

- Language: Python 3.11+
- Formatting: Follow PEP 8, use Black or similar formatter
- Type hints: Use type annotations throughout
- Naming: snake_case for variables/functions, PascalCase for classes
- Env files: use `.env` in `python/agent/` (never commit secrets)

## Testing Guidelines

- Framework: pytest (when adding tests)
- Aim for unit tests on bot handlers and worker functions
- Mock Telegram bot and Supabase clients in tests
- Keep coverage pragmatic for critical paths

## Commit & Pull Request Guidelines

- Commits: imperative mood, concise subject (<72 chars), scoped when helpful (e.g., "bot:", "worker:")
- PRs: clear description, link issues, list env/config changes, add screenshots or sample updates where relevant (e.g., bot responses), and test notes

## Security & Configuration Tips

- Required env vars: `BOT_TOKEN`, `WEBHOOK_SECRET`, `PUBLIC_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE`
- Validate env via `python/agent/settings.py`
- Keep webhook handlers fast; offload heavy work to background worker
- For local webhooks, use a tunnel (e.g., ngrok) then run: `PUBLIC_URL=https://... python set_webhook.py`

## Prisma Setup

- Add `DATABASE_URL` and `DIRECT_URL` in `.env.local` using Supabase connection strings
- Schema at `prisma/schema.prisma` defines `jobs` and `sessions` tables
- Commands: `pnpm prisma:generate`, `pnpm prisma:migrate --name <msg>`, `pnpm prisma:deploy`
- Prefer migrations via Prisma; avoid manual SQL DDL

## Roadmap

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

Notes

- Focus on map data quality and operator UX
- Keep webhook handlers fast; defer heavy work to `worker.py`
