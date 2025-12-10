# Changelog

## [0.4.0] - Simplified Directory Structure

### Changed

- **Flattened project structure** - Moved all Python code from `python/agent/` to root level
- **Consolidated documentation** - Merged multiple READMEs into single root README
- **Removed unused files** - Deleted `run_worker.py` (worker starts from main.py)

### Project Structure

```
omnimap-agent/
├── adapters/           # Platform messaging adapters
├── prisma/             # Database schema & migrations
├── main.py             # FastAPI app entry point
├── worker.py           # Unified job processor
├── bot_handlers.py     # Telegram command handlers
├── settings.py         # Environment configuration
├── supabase_client.py  # Supabase REST client
├── set_webhook.py      # Webhook setup script
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container build
├── README.md           # Documentation
└── CHANGELOG.md        # This file
```

---

## [0.3.0] - Multi-Platform Messaging Architecture

### Major Changes

**Added multi-platform adapter system** - The agent now supports sending and receiving messages from multiple chat platforms through a unified adapter interface:

- ✅ Telegram (fully implemented)
- ✅ Instagram Messenger (ready for Meta Graph API)
- ✅ TikTok (scaffolded, limited API availability)

### Added

#### Adapter System (`adapters/`)

- **`base.py`**: Core abstractions for messaging:

  - `MessagingAdapter` - Abstract base class for platform adapters
  - `IncomingMessage` - Normalized incoming message format
  - `OutgoingMessage` - Platform-agnostic outgoing message
  - `MessageDeliveryResult` - Delivery status and metadata
  - `AdapterCapabilities` - Platform feature detection
  - `Platform` enum - Supported platforms

- **`registry.py`**: Adapter management:

  - `AdapterRegistry` - Central registry for all adapters
  - `get_adapter_registry()` - Global registry accessor
  - Lifecycle management (initialize/shutdown)

- **`telegram.py`**: Telegram adapter implementation:

  - Full send/receive support
  - Inline keyboard buttons
  - Media support
  - Reply context
  - Webhook signature validation

- **`instagram.py`**: Instagram Messenger adapter:

  - Meta Graph API integration
  - Quick replies support
  - Media attachments
  - HMAC-SHA256 webhook validation

- **`tiktok.py`**: TikTok adapter scaffold:
  - Comment event parsing
  - Future direct message support
  - OAuth token utilities

#### New Webhook Endpoints

- `GET/POST /api/instagram` - Instagram webhook (with Meta verification)
- `GET/POST /api/tiktok` - TikTok webhook (with challenge verification)

#### Enhanced Configuration

- **`settings.py`**: Multi-platform credentials:
  - `TelegramSettings` - Bot token, webhook secret
  - `InstagramSettings` - Access token, app secret, account ID
  - `TikTokSettings` - Client key/secret, access token
  - `enabled_platforms` property

### Changed

- **`worker.py`**: Platform-agnostic job processing:

  - Uses `AdapterRegistry` instead of direct `telegram.Bot`
  - `_get_platform_from_job()` - Determines target platform
  - `_send_message()` - Routes through adapter registry
  - Job results include platform information

- **`main.py`**: Adapter initialization:

  - `_initialize_adapters()` - Sets up all configured adapters
  - Registry available throughout application
  - Health check returns enabled platforms

- **`supabase_client.py`**: Added `get_session()` method

---

## [0.2.0] - Migration to Unified Python Architecture

### Major Changes

**Removed Next.js wrapper** - The entire Next.js application has been replaced with a pure Python FastAPI service.

**Consolidated workers** - Previously there were two separate workers (TypeScript and Python). Now there's a single Python worker that handles all job types.

### Added

- **`main.py`**: FastAPI application with webhook endpoint and health check
- **`bot_handlers.py`**: Telegram command handlers
- **`worker.py`**: Unified job processor
- **`supabase_client.py`**: Session management
- **`settings.py`**: Environment configuration
- **`set_webhook.py`**: Webhook setup script

### Technical Details

#### Job Processing Flow

1. User sends command to Telegram bot
2. Telegram forwards update to webhook endpoint
3. Bot handler processes command, may create job in Supabase
4. Background worker polls for queued jobs
5. Worker processes job, updates status
6. Worker may create follow-up jobs (e.g., `notify_user`)
7. User receives response in Telegram
