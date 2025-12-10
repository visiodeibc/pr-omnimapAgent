import logging
from threading import Thread
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from adapters.base import Platform
from adapters.instagram import InstagramAdapter
from adapters.registry import AdapterRegistry, get_adapter_registry
from adapters.telegram import TelegramAdapter
from adapters.tiktok import TikTokAdapter
from bot_handlers import button_callback, hello_command, help_command, start_command
from settings import get_settings
from supabase_client import SupabaseRestClient
from worker import UnifiedWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="OmniMap Python Agent", version="0.3.0")
_worker_thread: Optional[Thread] = None
_bot_application: Optional[Application] = None


def _initialize_adapters(settings, bot: Optional[Any] = None) -> AdapterRegistry:
    """
    Initialize and register all configured platform adapters.

    Args:
        settings: Application settings containing platform credentials.
        bot: Telegram bot instance (if Telegram is configured).

    Returns:
        Configured adapter registry.
    """
    registry = get_adapter_registry()

    # Register Telegram adapter
    if settings.telegram and bot:
        telegram_adapter = TelegramAdapter(bot)
        registry.register(telegram_adapter)
        logger.info("Registered Telegram adapter")

    # Register Instagram adapter
    if settings.instagram:
        instagram_adapter = InstagramAdapter(
            access_token=settings.instagram.access_token,
            app_secret=settings.instagram.app_secret,
            instagram_account_id=settings.instagram.account_id,
        )
        registry.register(instagram_adapter)
        logger.info("Registered Instagram adapter")

    # Register TikTok adapter
    if settings.tiktok:
        tiktok_adapter = TikTokAdapter(
            client_key=settings.tiktok.client_key,
            client_secret=settings.tiktok.client_secret,
            access_token=settings.tiktok.access_token,
        )
        registry.register(tiktok_adapter)
        logger.info("Registered TikTok adapter")

    return registry


@app.on_event("startup")
async def startup() -> None:
    """Initialize bot, adapters, and start worker on startup."""
    settings = get_settings()

    # Initialize Telegram bot application
    global _bot_application  # noqa: PLW0603
    _bot_application = (
        Application.builder().token(settings.telegram.bot_token).updater(None).build()
    )

    # Store Supabase client in bot_data for handlers
    supabase_client = SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    _bot_application.bot_data["supabase_client"] = supabase_client

    # Register command handlers
    _bot_application.add_handler(CommandHandler("start", start_command))
    _bot_application.add_handler(CommandHandler("help", help_command))
    _bot_application.add_handler(CommandHandler("hello", hello_command))

    # Register callback query handler for inline buttons
    _bot_application.add_handler(CallbackQueryHandler(button_callback))

    # Initialize the bot application
    await _bot_application.initialize()
    await _bot_application.start()
    logger.info("Telegram bot initialized successfully")

    # Initialize all platform adapters
    adapter_registry = _initialize_adapters(settings, _bot_application.bot)
    logger.info("Enabled platforms: %s", settings.enabled_platforms)

    # Start background worker if enabled
    if not settings.enable_worker:
        logger.info("Python worker disabled via environment flag")
        return

    worker = UnifiedWorker(settings, adapter_registry)
    thread = Thread(target=worker.run_forever, name="python-worker", daemon=True)
    thread.start()
    global _worker_thread  # noqa: PLW0603
    _worker_thread = thread
    logger.info("Python worker thread started")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Cleanup on shutdown."""
    # Shutdown adapters
    registry = get_adapter_registry()
    import asyncio

    loop = asyncio.get_event_loop()
    await registry.shutdown_all()

    if _bot_application:
        await _bot_application.stop()
        await _bot_application.shutdown()
        logger.info("Telegram bot shut down")


@app.get("/health")
def healthcheck() -> dict[str, Any]:
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "ok",
        "bot": "omnimap-agent",
        "version": "0.3.0",
        "platforms": settings.enabled_platforms,
    }


# =============================================================================
# Telegram Webhook
# =============================================================================


@app.post("/api/tg")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Handle incoming Telegram webhook updates."""
    settings = get_settings()

    # Verify webhook secret
    if x_telegram_bot_api_secret_token != settings.telegram.webhook_secret:
        logger.error("Invalid webhook secret token")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Parse the update
    try:
        data = await request.json()
        update = Update.de_json(data, _bot_application.bot)
    except Exception as exc:
        logger.error("Failed to parse update: %s", exc)
        raise HTTPException(status_code=400, detail="Bad Request") from exc

    # Process the update
    try:
        await _bot_application.process_update(update)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Error processing update: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# =============================================================================
# Instagram Webhook
# =============================================================================


@app.get("/api/instagram")
async def instagram_webhook_verify(
    request: Request,
) -> Any:
    """
    Handle Instagram webhook verification (GET request).

    Meta requires this endpoint to respond to a verification challenge
    when setting up the webhook.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    settings = get_settings()

    # Use app secret as verify token for simplicity, or configure a separate one
    verify_token = (
        settings.instagram.app_secret if settings.instagram else None
    ) or "omnimap_verify"

    if mode == "subscribe" and token == verify_token:
        logger.info("Instagram webhook verified successfully")
        return int(challenge) if challenge else ""

    logger.warning("Instagram webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/instagram")
async def instagram_webhook(request: Request) -> dict[str, Any]:
    """Handle incoming Instagram messenger webhook events."""
    settings = get_settings()

    if not settings.instagram:
        logger.warning("Received Instagram webhook but Instagram is not configured")
        raise HTTPException(status_code=501, detail="Instagram not configured")

    # Get the adapter for signature validation and parsing
    registry = get_adapter_registry()
    adapter = registry.get(Platform.INSTAGRAM)

    if not adapter:
        raise HTTPException(status_code=501, detail="Instagram adapter not available")

    # Validate webhook signature
    body = await request.body()
    headers = dict(request.headers)
    if not adapter.validate_webhook(headers, body):
        logger.error("Invalid Instagram webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse the webhook payload
    try:
        data = await request.json()
        logger.info("Received Instagram webhook: %s", data.get("object", "unknown"))

        # Parse into normalized message
        incoming = adapter.parse_incoming(data)

        if incoming:
            logger.info(
                "Instagram message from %s: %s",
                incoming.user.platform_user_id,
                incoming.text[:50] if incoming.text else "(media)",
            )

            # TODO: Route to message handler pipeline
            # For now, just acknowledge receipt
            # Future: Create a job for processing, similar to Telegram

        return {"status": "ok"}

    except Exception as exc:
        logger.exception("Error processing Instagram webhook: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# =============================================================================
# TikTok Webhook
# =============================================================================


@app.get("/api/tiktok")
async def tiktok_webhook_verify(request: Request) -> Any:
    """
    Handle TikTok webhook verification (GET request).

    TikTok sends a challenge that must be echoed back.
    """
    params = request.query_params
    challenge = params.get("challenge")

    if challenge:
        logger.info("TikTok webhook verification challenge received")
        return {"challenge": challenge}

    raise HTTPException(status_code=400, detail="Missing challenge parameter")


@app.post("/api/tiktok")
async def tiktok_webhook(request: Request) -> dict[str, Any]:
    """Handle incoming TikTok webhook events."""
    settings = get_settings()

    if not settings.tiktok:
        logger.warning("Received TikTok webhook but TikTok is not configured")
        raise HTTPException(status_code=501, detail="TikTok not configured")

    # Get the adapter for signature validation and parsing
    registry = get_adapter_registry()
    adapter = registry.get(Platform.TIKTOK)

    if not adapter:
        raise HTTPException(status_code=501, detail="TikTok adapter not available")

    # Validate webhook signature
    body = await request.body()
    headers = dict(request.headers)
    if not adapter.validate_webhook(headers, body):
        logger.error("Invalid TikTok webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse the webhook payload
    try:
        data = await request.json()
        logger.info("Received TikTok webhook event: %s", data.get("event", "unknown"))

        # Parse into normalized message
        incoming = adapter.parse_incoming(data)

        if incoming:
            logger.info(
                "TikTok event from %s: %s",
                incoming.user.platform_user_id,
                incoming.metadata.get("event_type", "unknown"),
            )

            # TODO: Route to message handler pipeline
            # For now, just acknowledge receipt

        return {"status": "ok"}

    except Exception as exc:
        logger.exception("Error processing TikTok webhook: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# =============================================================================
# Generic Message Handler (for future unified processing)
# =============================================================================


async def handle_incoming_message(platform: Platform, data: dict) -> None:
    """
    Generic handler for incoming messages from any platform.

    This can be expanded to create jobs for processing, similar to how
    Telegram commands work.
    """
    registry = get_adapter_registry()
    adapter = registry.get(platform)

    if not adapter:
        logger.error("No adapter for platform: %s", platform.value)
        return

    incoming = adapter.parse_incoming(data)
    if not incoming:
        return

    # Log the message
    logger.info(
        "[%s] Message from %s: %s",
        platform.value,
        incoming.user.display_name,
        incoming.text[:100] if incoming.text else "(media)",
    )

    # TODO: Create session, create job, etc.
    # This is where you'd implement the unified message handling pipeline
