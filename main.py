from threading import Thread
from typing import Any, Optional

from dotenv import load_dotenv

# Load environment variables from .env file (must be before other local imports)
load_dotenv()

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from adapters.base import Platform
from adapters.instagram import InstagramAdapter
from adapters.registry import AdapterRegistry, get_adapter_registry
from adapters.telegram import TelegramAdapter
from adapters.tiktok import TikTokAdapter
from agents.orchestrator import AgentOrchestrator
from bot_handlers import callback_query_handler, hello_command, help_command, start_command
from debug_reporter import create_debug_reporter
from logging_config import get_logger, setup_logging
from settings import get_settings
from supabase_client import SupabaseRestClient
from worker import UnifiedWorker

# Initialize structured logging
setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="OmniMap Agent", version="0.5.0")
_worker_thread: Optional[Thread] = None
_bot_application: Optional[Application] = None
_agent_orchestrator: Optional[AgentOrchestrator] = None


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
    """Initialize bot, adapters, agent orchestrator, and start worker on startup."""
    settings = get_settings()

    logger.info(
        "Starting OmniMap Agent",
        extra={
            "environment": settings.environment,
            "agent_enabled": settings.agent_enabled,
        },
    )

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

    # Register callback query handler for inline keyboard buttons (onboarding navigation)
    _bot_application.add_handler(CallbackQueryHandler(callback_query_handler))
    logger.info("Registered callback query handler for onboarding buttons")

    # Register message handler for non-command text messages (routes to agent)
    # This handles regular text messages through the agentic pipeline
    _bot_application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            _handle_telegram_message,
        )
    )
    logger.info("Registered message handler for agentic processing")

    # Initialize the bot application
    await _bot_application.initialize()
    await _bot_application.start()
    logger.info("Telegram bot initialized successfully")

    # Initialize all platform adapters
    adapter_registry = _initialize_adapters(settings, _bot_application.bot)
    logger.info("Enabled platforms: %s", settings.enabled_platforms)

    # Initialize agent orchestrator if OpenAI is configured
    global _agent_orchestrator  # noqa: PLW0603
    if settings.openai:
        _agent_orchestrator = AgentOrchestrator(
            openai_api_key=settings.openai.api_key,
            model=settings.openai.model,
            supabase_client=supabase_client,
        )
        logger.info(
            "Agent orchestrator initialized",
            extra={"model": settings.openai.model},
        )
    else:
        logger.warning("OpenAI not configured, agentic workflow disabled")

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
        "version": "0.5.0",
        "environment": settings.environment,
        "platforms": settings.enabled_platforms,
        "agent_enabled": settings.agent_enabled,
    }


async def _handle_telegram_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle incoming Telegram text messages through the agent orchestrator.

    This handler processes non-command messages using the agentic pipeline:
    1. Check if user is new and needs onboarding welcome
    2. Parse message using TelegramAdapter
    3. Classify content with OpenAI
    4. Route to appropriate handler
    5. Optionally send response back to user

    Args:
        update: Telegram Update object
        context: Telegram context
    """
    from onboarding import CONDENSED_WELCOME

    if not update.message or not update.message.text:
        return

    settings = get_settings()
    registry = get_adapter_registry()
    adapter = registry.get(Platform.TELEGRAM)

    if not adapter:
        logger.warning("Telegram adapter not available for message processing")
        return

    # Convert Update to raw payload for adapter parsing
    raw_payload = update.to_dict()
    incoming = adapter.parse_incoming(raw_payload)

    if not incoming:
        logger.debug("Could not parse Telegram message into IncomingMessage")
        return

    logger.info(
        "Processing Telegram message through agent pipeline",
        extra={
            "user_id": incoming.user.platform_user_id,
            "chat_id": incoming.chat.platform_chat_id,
            "content_preview": incoming.text[:50] if incoming.text else "(empty)",
        },
    )

    # Check if this is a new user who hasn't seen onboarding
    supabase_client: SupabaseRestClient = context.bot_data.get("supabase_client")
    should_show_welcome = False
    
    if supabase_client:
        try:
            # Check for existing session and onboarding status
            session, is_new_session = supabase_client.get_or_create_active_session(
                platform="telegram",
                platform_user_id=incoming.user.platform_user_id,
                platform_chat_id=int(incoming.chat.platform_chat_id) if incoming.chat.platform_chat_id else None,
                metadata={
                    "username": incoming.user.username,
                    "display_name": incoming.user.display_name,
                },
            )
            
            # Show welcome if this is a brand new user who hasn't seen onboarding
            if is_new_session and not supabase_client.has_seen_onboarding(session["id"]):
                should_show_welcome = True
                # Mark that we're showing the condensed onboarding
                supabase_client.mark_onboarding_shown(session["id"])
                logger.info(
                    "New user detected, will show condensed welcome",
                    extra={"user_id": incoming.user.platform_user_id},
                )
        except Exception as exc:
            logger.warning("Failed to check onboarding status: %s", exc)

    # Create debug reporter for development mode
    debug_reporter = create_debug_reporter(
        chat_id=incoming.chat.platform_chat_id,
        platform=Platform.TELEGRAM,
        adapter_registry=registry,
        environment=settings.environment,
    )

    if debug_reporter.enabled:
        debug_reporter.info(
            "Telegram message received",
            data={
                "from": incoming.user.display_name,
                "text": (incoming.text or "")[:100],
            },
        )

    # Send condensed welcome to new users first
    if should_show_welcome:
        await update.message.reply_text(CONDENSED_WELCOME, parse_mode="HTML")

    # Process through agent orchestrator if available
    if _agent_orchestrator:
        try:
            result = await _agent_orchestrator.process_incoming_message(
                incoming,
                debug_reporter=debug_reporter,
            )

            logger.info(
                "Agent processed Telegram message",
                extra={
                    "handler": result.handler_name,
                    "content_type": result.content_type.value,
                    "success": result.success,
                },
            )

            # Flush debug logs to user in dev mode
            if debug_reporter.enabled:
                await debug_reporter.flush()

            # Send response to user if handler provided a message
            # Use HTML parse_mode to support formatting like <b>bold</b>
            if result.message:
                await update.message.reply_text(result.message, parse_mode="HTML")

        except Exception as exc:
            logger.exception("Error processing message through agent: %s", exc)
            if debug_reporter.enabled:
                debug_reporter.error("Agent processing failed", data={"error": str(exc)})
                await debug_reporter.flush()
    else:
        # No orchestrator available
        if debug_reporter.enabled:
            debug_reporter.warn("Agent orchestrator not available")
            await debug_reporter.flush()

        logger.debug("Agent orchestrator not available, skipping message processing")


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
# Common Webhook Processing
# =============================================================================


async def _process_platform_webhook(
    platform: Platform,
    adapter: Any,
    data: dict,
) -> dict[str, Any]:
    """
    Common webhook processing logic for all platforms.

    Parses incoming message and routes through agent orchestrator.
    In development mode, sends debug logs back to the user.

    Args:
        platform: Source platform
        adapter: Platform adapter for parsing
        data: Raw webhook payload

    Returns:
        Response dict with processing status
    """
    settings = get_settings()
    incoming = adapter.parse_incoming(data)

    if not incoming:
        logger.debug(
            "Webhook payload was not a processable message",
            extra={"platform": platform.value},
        )
        return {"status": "ok", "processed": False}

    logger.info(
        "Message received",
        extra={
            "platform": platform.value,
            "user_id": incoming.user.platform_user_id,
            "content_preview": incoming.text[:50] if incoming.text else "(media)",
        },
    )

    # Create debug reporter for development mode
    debug_reporter = create_debug_reporter(
        chat_id=incoming.chat.platform_chat_id,
        platform=platform,
        adapter_registry=get_adapter_registry(),
        environment=settings.environment,
    )

    if debug_reporter.enabled:
        debug_reporter.info("Message received", data={
            "from": incoming.user.display_name,
            "text": (incoming.text or "")[:100],
        })

    # Process through agent orchestrator if available
    if _agent_orchestrator:
        result = await _agent_orchestrator.process_incoming_message(
            incoming,
            debug_reporter=debug_reporter,
        )
        logger.info(
            "Agent processed message",
            extra={
                "platform": platform.value,
                "handler": result.handler_name,
                "content_type": result.content_type.value,
                "success": result.success,
            },
        )

        # Flush debug logs to user in dev mode
        if debug_reporter.enabled:
            await debug_reporter.flush()

        return {"status": "ok", "processed": True, "content_type": result.content_type.value}

    # No orchestrator - just send debug info if in dev mode
    if debug_reporter.enabled:
        debug_reporter.warn("Agent orchestrator not available")
        debug_reporter.info("Message echo", data={"text": incoming.text})
        await debug_reporter.flush()

    logger.debug("Agent orchestrator not available, skipping processing")
    return {"status": "ok", "processed": False}


# =============================================================================
# Instagram Webhook
# =============================================================================


@app.get("/api/instagram")
async def instagram_webhook_verify(request: Request) -> Any:
    """Handle Instagram webhook verification (GET request)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    settings = get_settings()
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
        raise HTTPException(status_code=501, detail="Instagram not configured")

    registry = get_adapter_registry()
    adapter = registry.get(Platform.INSTAGRAM)
    if not adapter:
        raise HTTPException(status_code=501, detail="Instagram adapter not available")

    # Validate webhook signature
    body = await request.body()
    if not adapter.validate_webhook(dict(request.headers), body):
        logger.error("Invalid Instagram webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = await request.json()
        return await _process_platform_webhook(Platform.INSTAGRAM, adapter, data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error processing Instagram webhook", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# =============================================================================
# TikTok Webhook
# =============================================================================


@app.get("/api/tiktok")
async def tiktok_webhook_verify(request: Request) -> Any:
    """Handle TikTok webhook verification (GET request)."""
    challenge = request.query_params.get("challenge")
    if challenge:
        logger.info("TikTok webhook verification challenge received")
        return {"challenge": challenge}
    raise HTTPException(status_code=400, detail="Missing challenge parameter")


@app.post("/api/tiktok")
async def tiktok_webhook(request: Request) -> dict[str, Any]:
    """Handle incoming TikTok webhook events."""
    settings = get_settings()

    if not settings.tiktok:
        raise HTTPException(status_code=501, detail="TikTok not configured")

    registry = get_adapter_registry()
    adapter = registry.get(Platform.TIKTOK)
    if not adapter:
        raise HTTPException(status_code=501, detail="TikTok adapter not available")

    # Validate webhook signature
    body = await request.body()
    if not adapter.validate_webhook(dict(request.headers), body):
        logger.error("Invalid TikTok webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = await request.json()
        return await _process_platform_webhook(Platform.TIKTOK, adapter, data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error processing TikTok webhook", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# =============================================================================
# Unified Webhook Endpoint
# =============================================================================


@app.post("/api/message")
async def unified_message_webhook(request: Request) -> dict[str, Any]:
    """
    Unified webhook endpoint for testing and forwarding.

    Expects JSON body with:
    - platform: 'telegram' | 'instagram' | 'tiktok'
    - payload: Platform-specific webhook payload

    Note: This endpoint does NOT validate signatures (use for testing only).
    """
    try:
        data = await request.json()
        platform_str = data.get("platform")
        payload = data.get("payload")

        if not platform_str or not payload:
            raise HTTPException(
                status_code=400,
                detail="Missing 'platform' or 'payload' in request body",
            )

        try:
            platform = Platform(platform_str.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {platform_str}")

        logger.info("Received unified webhook", extra={"platform": platform.value})

        registry = get_adapter_registry()
        adapter = registry.get(platform)
        if not adapter:
            return {"status": "error", "reason": f"No adapter for platform: {platform.value}"}

        return await _process_platform_webhook(platform, adapter, payload)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error processing unified webhook", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Internal server error") from exc
