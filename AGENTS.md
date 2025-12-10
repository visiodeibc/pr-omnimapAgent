# Repository Guidelines

## Project Structure

```
omnimap-agent/
├── adapters/              # Platform messaging adapters
│   ├── base.py            # Abstract interfaces & types
│   ├── registry.py        # Adapter management
│   ├── telegram.py        # Telegram adapter
│   ├── instagram.py       # Instagram adapter
│   └── tiktok.py          # TikTok adapter
├── prisma/                # Database schema & migrations
│   ├── schema.prisma
│   └── migrations/
├── main.py                # FastAPI app with webhook endpoints
├── worker.py              # Unified background job processor
├── bot_handlers.py        # Telegram command handlers
├── settings.py            # Environment configuration (Pydantic)
├── supabase_client.py     # Supabase REST API client
├── set_webhook.py         # Webhook setup script
├── requirements.txt       # Python dependencies
└── Dockerfile             # Container build
```

## Build & Development Commands

```bash
# Install dependencies
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

## Coding Style

- Language: Python 3.11+
- Formatting: PEP 8, use Black formatter
- Type hints: Use annotations throughout
- Naming: snake_case for variables/functions, PascalCase for classes
- Env files: use `.env` at root (never commit secrets)

## Testing Guidelines

- Framework: pytest
- Mock Telegram bot and Supabase clients in tests
- Focus on bot handlers and worker functions

## Commit & PR Guidelines

- Commits: imperative mood, concise (<72 chars)
- Scope when helpful (e.g., "bot:", "worker:", "adapters:")
- PRs: clear description, link issues, list env/config changes

## Security & Configuration

Required env vars:

- `BOT_TOKEN`, `WEBHOOK_SECRET`, `PUBLIC_URL`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE`

Optional:

- `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCOUNT_ID`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_ACCESS_TOKEN`
- `PYTHON_WORKER_POLL_INTERVAL`, `PYTHON_WORKER_ENABLED`

## Roadmap

### Phase 1 — Extraction

- [x] Instagram Reels/Post → candidate places with Google Maps links
- [ ] Accept other inputs (plain text, websites) to extract places
- [ ] Export results as JSON/CSV for downstream use

### Phase 2 — Enrichment

- [ ] Enrich places via Google Places/OpenStreetMap details
- [ ] De-duplicate/merge candidates; confidence scoring
- [ ] Region hints and language handling

### Phase 3 — Update Suggestions

- [ ] Generate suggested map updates (e.g., OSM edits) for review
- [ ] Human-in-the-loop review flows inside Telegram
- [ ] Track applied/approved suggestions

### Phase 4 — Usage & Billing (optional)

- [ ] Usage logging and quotas
- [ ] Team sharing / collaboration
- [ ] Billing integration if needed

## Notes

- Focus on map data quality and operator UX
- Keep webhook handlers fast; defer heavy work to `worker.py`
- Adapters provide platform abstraction for multi-platform support
