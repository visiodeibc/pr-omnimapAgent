# 🗺️ OmniMap Agent

A multi-platform messaging bot built with **Python (FastAPI)** and **Supabase**, designed to extract places from content (Instagram Reels, TikTok, etc.) and turn them into useful map links.

## ✨ Features

- 🚀 **Cloud-ready**: Deploy to Google Cloud Run, Docker, or any container platform
- 🐍 **Pure Python**: FastAPI + python-telegram-bot for webhook handling
- 🔄 **Unified worker**: Single background worker handles all job types
- 🗄️ **Supabase integration**: Persistent storage and background job processing
- 🔒 **Secure**: Webhook secret validation and environment variable validation
- 🌐 **Multi-platform**: Telegram (full), Instagram (ready), TikTok (scaffold)
- 🧠 **Conversation Memory**: Session-based context (30-min window) for contextual responses

## 📁 Project Structure

```
omnimap-agent/
├── adapters/              # Platform messaging adapters
│   ├── base.py            # Abstract interfaces & types
│   ├── registry.py        # Adapter management
│   ├── telegram.py        # Telegram adapter (full)
│   ├── instagram.py       # Instagram adapter (ready)
│   └── tiktok.py          # TikTok adapter (scaffold)
├── agents/                # Agentic workflow components
│   ├── handlers.py        # Content-type specific handlers
│   ├── orchestrator.py    # Main agent orchestrator (with memory integration)
│   └── types.py           # Types & OpenAI function definitions
├── services/              # Internal services
│   ├── google_places.py   # Google Places API integration
│   └── memory.py          # Conversation memory service
├── prisma/                # Database schema & migrations
│   ├── schema.prisma
│   └── migrations/
├── main.py                # FastAPI app + webhook endpoints
├── worker.py              # Unified job processor
├── bot_handlers.py        # Telegram command handlers
├── settings.py            # Multi-platform configuration
├── supabase_client.py     # Supabase REST client (with memory operations)
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
ENVIRONMENT=local
LOG_LEVEL=INFO
# Force-enable/disable in-chat debug reports (default: enabled outside production)
# DEBUG_REPORTER_ENABLED=false

# Instagram (optional)
INSTAGRAM_ACCESS_TOKEN=your_page_access_token
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_ACCOUNT_ID=your_account_id
INSTAGRAM_VERIFY_TOKEN=your_verify_token
# Optional: per-account token map (JSON object)
# INSTAGRAM_ACCESS_TOKEN_MAP={"17841467615207225":"EAAG..."}

# TikTok (optional)
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret

# Facebook OAuth (optional)
FACEBOOK_APP_ID=your_facebook_app_id
FACEBOOK_APP_SECRET=your_facebook_app_secret
FACEBOOK_REDIRECT_URI=https://your-backend-domain.com/auth/facebook/callback
FACEBOOK_LOGIN_SCOPES=pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging,instagram_manage_messages,instagram_business_manage_messages
FACEBOOK_GRAPH_API_VERSION=v24.0
FACEBOOK_ALLOWED_RETURN_URLS=https://your-frontend-domain.com/auth/facebook/connect,http://localhost:3000/auth/facebook/connect
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

# Terminal 3: Set webhook [if they are changed or not set]
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

| Endpoint                   | Method | Description                               |
| -------------------------- | ------ | ----------------------------------------- |
| `/health`                  | GET    | Health check                              |
| `/auth/facebook/login`     | GET    | Start Facebook OAuth flow                 |
| `/auth/facebook/callback`  | GET    | Exchange code and return JSON or redirect |
| `/auth/facebook/subscribe` | POST   | Subscribe selected page to app            |
| `/api/tg`                  | POST   | Telegram webhook                          |
| `/api/instagram`           | GET    | Instagram webhook verification            |
| `/api/instagram`           | POST   | Instagram webhook events                  |
| `/api/tiktok`              | GET    | TikTok webhook verification               |
| `/api/tiktok`              | POST   | TikTok webhook events                     |

### Facebook OAuth flow for hosted testing

1. Configure your Meta app with:
   - Valid OAuth Redirect URI: `https://<agent-domain>/auth/facebook/callback`
   - Requested scopes including `pages_read_engagement,pages_manage_metadata`
2. Set backend env vars from the block above.
3. Open:
   - `https://<agent-domain>/auth/facebook/login?return_to=https://<frontend-domain>/auth/facebook/connect&include_page_tokens=true`
4. After approval, backend redirects to the frontend `return_to` URL with connection status and selected token fields in query params.

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

## 🧠 Content Handlers

The agentic workflow classifies incoming messages and routes them to specialized handlers. Each handler processes a specific content type and returns a structured `HandlerResult`.

### Content Types & Handlers

| Content Type        | Handler                 | Description                                              |
| ------------------- | ----------------------- | -------------------------------------------------------- |
| 📍 `PLACE_NAME`     | `handle_place_name`     | Direct place name mentions (e.g., "Cafe Central Vienna") |
| ❓ `QUESTION`       | `handle_question`       | Questions about places, usage, or general queries        |
| 📸 `INSTAGRAM_LINK` | `handle_instagram_link` | Instagram post/reel links for place extraction           |
| 🎵 `TIKTOK_LINK`    | `handle_tiktok_link`    | TikTok video links for place extraction                  |
| 🔗 `OTHER_LINK`     | `handle_other_link`     | Other URLs (articles, map links, business listings)      |
| ❔ `UNKNOWN`        | `handle_unknown`        | Unclassified messages requiring clarification            |

### Handler Flow

```
User Message
     │
     ▼
┌─────────────────┐
│  Orchestrator   │  ← Classifies content using LLM
│  (classify)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ dispatch_handler│  ← Routes to appropriate handler
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Content Handler │  ← Processes content, queues follow-up jobs
│ (e.g., IG link) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ HandlerResult   │  ← Returns structured result with data & actions
└─────────────────┘
```

### Handler Responsibilities

Each handler follows a consistent pattern:

1. **Log** the incoming request with relevant metadata
2. **Process** the content (fetch external data, extract places, etc.)
3. **Store** results and queue follow-up jobs
4. **Return** a `HandlerResult` with:
   - `success`: Whether processing succeeded
   - `data`: Extracted/processed data
   - `message`: User-facing response
   - `follow_up_actions`: Jobs to queue for further processing

### Example: Instagram Link Handler

When a user sends an Instagram link:

```
Input: https://instagram.com/p/ABC123

1. Extract content ID and username from URL
2. Fetch Instagram post/reel content via API
3. Extract location tags from the post
4. Extract place mentions from caption text
5. Queue jobs: fetch_instagram_content, extract_location_tags, extract_places_from_caption
6. Return HandlerResult with extracted data
```

## 🧠 Conversation Memory

The agent maintains conversation context to provide better, more contextual responses.

### Session-Based Memory (30-Minute Window)

Conversations are grouped into sessions based on activity:

- **Active Session**: If the user sends a message within 30 minutes of their last message, the conversation continues in the same session with full context.
- **New Session**: After 30+ minutes of inactivity, old memories are archived and a fresh session starts.

```
User Message
     │
     ▼
┌─────────────────────┐
│  Session Manager    │  ← Check last_message_at
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    │           │
< 30 min    ≥ 30 min
    │           │
    ▼           ▼
Continue    Archive old
session     memories &
    │       start fresh
    │           │
    └─────┬─────┘
          ▼
┌─────────────────────┐
│  Load Context       │  ← Recent messages for LLM
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Classify with      │  ← Context-aware classification
│  Conversation       │
└─────────────────────┘
```

### Memory Storage

Conversation memories are stored in the `session_memories` table:

| Field        | Description                         |
| ------------ | ----------------------------------- |
| `session_id` | Links to user session               |
| `role`       | `user` or `assistant`               |
| `kind`       | Message type (e.g., `message`)      |
| `content`    | JSON with message text and metadata |
| `archived`   | `true` when session expires         |

### Context in Classification

When classifying messages, the LLM receives recent conversation history to:

- Understand references to previous messages (e.g., "that place", "the restaurant I mentioned")
- Maintain context for follow-up questions
- Provide more accurate classifications based on conversation flow

### Agent Memory Functions (Future)

The agent can use these functions for explicit memory operations:

- **`query_memory`**: Search conversation history for relevant context
- **`save_to_memory`**: Save important information for long-term recall (preferences, frequently mentioned places)

## 🔮 Future: Long-term Memory (RAG)

The current session-based memory is Phase 1. Future phases will implement semantic memory retrieval:

### Planned Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Memory System                      │
├─────────────────────────────────────────────────────┤
│  Session Memory (Current)                           │
│  - 30-minute conversation window                    │
│  - Recent messages in context                       │
│  - Archived when session expires                    │
├─────────────────────────────────────────────────────┤
│  Long-term Memory (Planned)                         │
│  - pgvector for semantic embeddings                 │
│  - OpenAI embeddings for message content            │
│  - Similarity search for relevant historical context│
│  - Memory importance scoring                        │
│  - User preferences persistence                     │
└─────────────────────────────────────────────────────┘
```

### RAG Implementation Plan

1. **Vector Storage**: Use Supabase pgvector extension
2. **Embeddings**: Generate OpenAI embeddings for important messages
3. **Retrieval**: Semantic search for relevant past conversations
4. **Scoring**: Rank memories by relevance and importance
5. **Context Injection**: Include relevant memories in LLM prompts

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
