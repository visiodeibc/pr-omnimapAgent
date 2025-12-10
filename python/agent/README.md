# OmniMap Python Agent

**Unified Python service** for multi-platform messaging that handles webhooks, bot commands, and job processing through Supabase. Supports Telegram, Instagram Messenger, and TikTok.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python FastAPI Agent                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Webhooks:                                                 │  │
│  │   POST /api/tg       - Telegram                          │  │
│  │   POST /api/instagram - Instagram Messenger              │  │
│  │   POST /api/tiktok   - TikTok                            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Adapter Registry                                         │  │
│  │   - Platform-agnostic message routing                    │  │
│  │   - Unified IncomingMessage/OutgoingMessage format       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Unified Worker                                           │  │
│  │   - Processes jobs from Supabase queue                   │  │
│  │   - Routes responses to correct platform                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Supported Platforms

| Platform  | Status      | Send | Receive | Rich Content   |
| --------- | ----------- | ---- | ------- | -------------- |
| Telegram  | ✅ Full     | ✅   | ✅      | Buttons, Media |
| Instagram | ✅ Ready    | ✅   | ✅      | Quick Replies  |
| TikTok    | 🚧 Scaffold | ⚠️   | ✅      | Comments only  |

## Features

- ✅ Multi-platform webhook handling
- ✅ Platform-agnostic adapter system
- ✅ Bot commands: `/start`, `/help`, `/hello`
- ✅ Inline keyboard support (Telegram)
- ✅ Unified job processor for all platforms:
  - `python_hello` - Hello world demo
  - `notify_user` - Send messages to any platform
  - `echo_job` - Echo test jobs
- ✅ Session management with Supabase
- ✅ Session memory tracking

## Quickstart

### Local Development

```bash
# Navigate to agent directory
cd python/agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and configure
cp .env.example .env
# Edit .env with your values

# Run the service
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

### Environment Variables

#### Required (Core)

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE=your_service_role_key
PUBLIC_URL=https://your-domain.com
```

#### Telegram (Required for now)

```bash
BOT_TOKEN=your_telegram_bot_token
WEBHOOK_SECRET=your_random_webhook_secret
```

#### Instagram (Optional)

```bash
INSTAGRAM_ACCESS_TOKEN=your_page_access_token
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_ACCOUNT_ID=your_instagram_account_id
```

#### TikTok (Optional)

```bash
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_ACCESS_TOKEN=your_access_token  # Optional
```

#### Worker Settings

```bash
PYTHON_WORKER_POLL_INTERVAL=5  # Seconds (default: 5)
PYTHON_WORKER_ENABLED=true      # Enable/disable worker
```

### Setting Up Webhooks

#### Telegram

```bash
# With environment variables set
python set_webhook.py

# Or with explicit URL
PUBLIC_URL=https://your-domain.com python set_webhook.py
```

#### Instagram

1. Create a Meta App at https://developers.facebook.com/
2. Add Instagram Messaging product
3. Configure webhook URL: `https://your-domain.com/api/instagram`
4. Set verify token to your `INSTAGRAM_APP_SECRET`
5. Subscribe to `messages` webhook field

#### TikTok

1. Create TikTok Developer App
2. Configure webhook URL: `https://your-domain.com/api/tiktok`
3. The endpoint handles challenge verification automatically

## Deployment

### Google Cloud Run

```bash
gcloud run deploy omnimap-python-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars BOT_TOKEN=xxx,WEBHOOK_SECRET=yyy,SUPABASE_URL=zzz,SUPABASE_SERVICE_ROLE=aaa,PUBLIC_URL=https://your-service.run.app
```

### Docker

```bash
# Build
docker build -t omnimap-agent .

# Run
docker run -p 8080:8080 \
  -e BOT_TOKEN=xxx \
  -e WEBHOOK_SECRET=yyy \
  -e SUPABASE_URL=zzz \
  -e SUPABASE_SERVICE_ROLE=aaa \
  -e PUBLIC_URL=https://your-domain.com \
  omnimap-agent
```

## API Endpoints

| Endpoint         | Method | Description                              |
| ---------------- | ------ | ---------------------------------------- |
| `/health`        | GET    | Health check (returns enabled platforms) |
| `/api/tg`        | POST   | Telegram webhook                         |
| `/api/instagram` | GET    | Instagram webhook verification           |
| `/api/instagram` | POST   | Instagram webhook events                 |
| `/api/tiktok`    | GET    | TikTok webhook verification              |
| `/api/tiktok`    | POST   | TikTok webhook events                    |

## Project Structure

```
python/agent/
├── main.py              # FastAPI app + webhook endpoints
├── bot_handlers.py      # Telegram command handlers
├── worker.py            # Unified job processor
├── supabase_client.py   # Supabase REST API client
├── settings.py          # Multi-platform configuration
├── set_webhook.py       # Telegram webhook setup script
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container image
├── adapters/            # Platform adapters
│   ├── __init__.py      # Exports
│   ├── base.py          # Abstract interfaces
│   ├── registry.py      # Adapter management
│   ├── telegram.py      # Telegram adapter
│   ├── instagram.py     # Instagram adapter
│   ├── tiktok.py        # TikTok adapter
│   └── README.md        # Adapter documentation
└── README.md            # This file
```

## Development

### Adding New Platforms

See [adapters/README.md](adapters/README.md) for detailed instructions.

Quick overview:

1. Create adapter class implementing `MessagingAdapter`
2. Register in `main.py:_initialize_adapters()`
3. Add webhook endpoint
4. Update settings for credentials

### Adding New Job Types

1. Add job type to `UnifiedWorker.HANDLED_TYPES` in `worker.py`
2. Create processor method `_process_<job_type>(self, job)`
3. Add routing in `_process_job()` method

Example:

```python
def _process_my_job(self, job: Dict[str, Any]) -> None:
    job_id = job["id"]
    platform = self._get_platform_from_job(job)
    chat_id = str(job.get("chat_id"))

    # Process job...

    # Send response to user on their platform
    self._send_message(
        chat_id=chat_id,
        text="Job complete!",
        platform=platform,
    )

    self._client.update_job(job_id, {"status": "completed"})
```

### Adding New Bot Commands

1. Create handler function in `bot_handlers.py`
2. Register handler in `main.py` startup function:

```python
_bot_application.add_handler(CommandHandler("mycommand", my_command_handler))
```

## Troubleshooting

### Webhook not receiving updates?

- Check `PUBLIC_URL` is correct and accessible
- Telegram: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
- Instagram: Check Meta App webhook configuration
- Check logs for authentication errors

### Worker not processing jobs?

- Ensure `PYTHON_WORKER_ENABLED=true`
- Check Supabase connection with service role key
- Verify jobs table has `queued` jobs

### Bot commands not responding?

- Check bot token is valid
- Verify handlers are registered in `main.py`
- Check FastAPI logs for errors

### Instagram messages not arriving?

- Verify Meta App has `instagram_manage_messages` permission
- Check webhook subscription is active
- Verify app secret matches for signature validation

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.
