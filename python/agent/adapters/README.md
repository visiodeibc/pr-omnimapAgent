# Messaging Adapters

This module provides a unified interface for sending and receiving messages across different chat platforms.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Application Layer                            │
│  (bot_handlers.py, worker.py, main.py)                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Adapter Registry                             │
│  - Routes messages to correct platform                          │
│  - Manages adapter lifecycle                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Telegram    │   │   Instagram   │   │    TikTok     │
│    Adapter    │   │    Adapter    │   │    Adapter    │
└───────────────┘   └───────────────┘   └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Telegram API  │   │  Meta Graph   │   │  TikTok API   │
│  (Bot API)    │   │     API       │   │               │
└───────────────┘   └───────────────┘   └───────────────┘
```

## Supported Platforms

| Platform  | Status      | Send Messages | Receive Messages | Rich Content      |
| --------- | ----------- | ------------- | ---------------- | ----------------- |
| Telegram  | ✅ Full     | ✅            | ✅               | ✅ Buttons, Media |
| Instagram | ✅ Ready    | ✅            | ✅               | ✅ Quick Replies  |
| TikTok    | 🚧 Scaffold | ⚠️ Limited    | ✅ Comments      | ❌                |

## Usage

### Sending Messages

```python
from adapters import get_adapter_registry, Platform
from adapters.base import OutgoingMessage

# Get the registry
registry = get_adapter_registry()

# Get adapter for a specific platform
adapter = registry.get(Platform.TELEGRAM)

# Send a simple text message
result = await adapter.send_text(chat_id="12345", text="Hello!")

# Or with more options
message = OutgoingMessage(
    chat_id="12345",
    text="Hello with buttons!",
    buttons=[
        {"text": "Option 1", "callback_data": "opt_1"},
        {"text": "Visit Site", "url": "https://example.com"},
    ],
)
result = await adapter.send_message(message)

if result.success:
    print(f"Sent! Message ID: {result.message_id}")
else:
    print(f"Failed: {result.error}")
```

### Parsing Incoming Messages

```python
from adapters import get_adapter_registry, Platform

registry = get_adapter_registry()
adapter = registry.get(Platform.INSTAGRAM)

# Parse a webhook payload
incoming = adapter.parse_incoming(webhook_data)

if incoming:
    print(f"From: {incoming.user.display_name}")
    print(f"Text: {incoming.text}")
    print(f"Platform: {incoming.platform.value}")
```

### Checking Capabilities

```python
adapter = registry.get(Platform.TELEGRAM)
caps = adapter.capabilities

if caps.supports_buttons:
    # Include inline buttons
    pass

if len(message_text) > caps.max_message_length:
    # Split the message
    pass
```

## Configuration

Each platform requires specific environment variables:

### Telegram (Required)

```bash
BOT_TOKEN=your_bot_token
WEBHOOK_SECRET=your_webhook_secret
```

### Instagram (Optional)

```bash
INSTAGRAM_ACCESS_TOKEN=your_page_access_token
INSTAGRAM_APP_SECRET=your_app_secret  # For webhook validation
INSTAGRAM_ACCOUNT_ID=your_instagram_account_id
```

### TikTok (Optional)

```bash
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_ACCESS_TOKEN=your_access_token  # Optional, for API calls
```

## Adding a New Platform

1. Create a new adapter file (e.g., `adapters/whatsapp.py`)
2. Implement the `MessagingAdapter` interface:

```python
from adapters.base import (
    MessagingAdapter,
    Platform,
    AdapterCapabilities,
    IncomingMessage,
    OutgoingMessage,
    MessageDeliveryResult,
)

class WhatsAppAdapter(MessagingAdapter):
    @property
    def platform(self) -> Platform:
        return Platform.WHATSAPP

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_buttons=True,
            supports_media=True,
            max_message_length=4096,
            # ... other capabilities
        )

    async def send_message(self, message: OutgoingMessage) -> MessageDeliveryResult:
        # Implement sending via WhatsApp API
        pass

    def parse_incoming(self, raw_payload: dict) -> Optional[IncomingMessage]:
        # Parse WhatsApp webhook format
        pass
```

3. Register the adapter in `main.py`:

```python
if settings.whatsapp:
    whatsapp_adapter = WhatsAppAdapter(...)
    registry.register(whatsapp_adapter)
```

4. Add webhook endpoint in `main.py`:

```python
@app.post("/api/whatsapp")
async def whatsapp_webhook(request: Request):
    # Handle WhatsApp webhooks
    pass
```

## Message Flow

### Incoming Message (Webhook → Handler)

```
1. Platform webhook hits /api/{platform}
2. Signature validated by adapter.validate_webhook()
3. Payload parsed by adapter.parse_incoming()
4. Normalized IncomingMessage passed to handler
5. Handler creates session + job for processing
```

### Outgoing Message (Worker → Platform)

```
1. Worker picks up job from queue
2. Determines platform from job/session
3. Gets adapter from registry
4. Calls adapter.send_message()
5. Updates job status based on result
```

## Testing

```python
# Mock adapter for testing
from adapters.base import MessagingAdapter, Platform

class MockAdapter(MessagingAdapter):
    def __init__(self):
        self.sent_messages = []

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    async def send_message(self, message):
        self.sent_messages.append(message)
        return MessageDeliveryResult(success=True, message_id="mock_123")

    def parse_incoming(self, raw_payload):
        return None

# Use in tests
from adapters.registry import reset_registry, get_adapter_registry

reset_registry()
registry = get_adapter_registry()
mock = MockAdapter()
registry.register(mock)

# Run your test...
assert len(mock.sent_messages) == 1
```
