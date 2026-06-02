import secrets
import json
import os
import re
from threading import Thread
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

# Load environment variables from .env file (must be before other local imports)
load_dotenv()

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from adapters.base import OutgoingMessage, Platform
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
from services.facebook_graph import FacebookGraphClient, build_oauth_url

# Initialize structured logging
setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="OmniMap Agent", version="0.5.0")
_worker_thread: Optional[Thread] = None
_bot_application: Optional[Application] = None
_agent_orchestrator: Optional[AgentOrchestrator] = None

FACEBOOK_STATE_COOKIE = "fb_oauth_state"
FACEBOOK_FLOW_COOKIE = "fb_oauth_flow"


def _safe_redirect_with_query(base_url: str, query_updates: dict[str, str]) -> str:
    parsed = urlparse(base_url)
    existing_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing_query.update(query_updates)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(existing_query),
            parsed.fragment,
        )
    )


def _is_allowed_return_url(return_to: str, allowed_urls: tuple[str, ...]) -> bool:
    if not allowed_urls:
        return False
    if not return_to.lower().startswith(("http://", "https://")):
        return False

    parsed_return = urlparse(return_to)
    if not parsed_return.netloc:
        return False

    normalized_return = (
        f"{parsed_return.scheme}://{parsed_return.netloc}{parsed_return.path}".rstrip("/")
    )
    for allowed in allowed_urls:
        parsed_allowed = urlparse(allowed)
        if not parsed_allowed.netloc:
            continue
        normalized_allowed = (
            f"{parsed_allowed.scheme}://{parsed_allowed.netloc}{parsed_allowed.path}".rstrip(
                "/"
            )
        )
        if normalized_return == normalized_allowed or normalized_return.startswith(
            f"{normalized_allowed}/"
        ):
            return True

    return False


def _build_callback_payload(
    payload: dict[str, Any],
    include_page_tokens: bool,
) -> dict[str, str]:
    pages = payload.get("pages") or []
    selected_page_id = payload.get("selected_page_id")
    selected_page = next(
        (page for page in pages if page.get("id") == selected_page_id),
        pages[0] if pages else None,
    )

    query_payload = {
        "status": "success",
        "selected_page_id": str(selected_page_id or ""),
        "selected_page_name": str((selected_page or {}).get("name", "")),
        "instagram_business_id": str(payload.get("instagram_business_id") or ""),
    }

    if include_page_tokens:
        query_payload["user_access_token"] = str(payload.get("user_access_token") or "")
        query_payload["page_access_token"] = str(
            (selected_page or {}).get("access_token", "")
        )

    if "persisted" in payload:
        query_payload["stored"] = "true" if payload.get("persisted") else "false"
    if payload.get("persist_error"):
        query_payload["store_error"] = str(payload.get("persist_error") or "")

    subscribed_result = payload.get("subscribed_result")
    if subscribed_result is not None:
        success = (
            subscribed_result.get("success")
            if isinstance(subscribed_result, dict)
            else None
        )
        if success is not None:
            query_payload["subscribed"] = "true" if success else "false"

    return query_payload


def _get_supabase_client() -> Optional[SupabaseRestClient]:
    client = getattr(app.state, "supabase_client", None)
    if client:
        return client
    if _bot_application and getattr(_bot_application, "bot_data", None):
        client = _bot_application.bot_data.get("supabase_client")
        if client:
            return client
    try:
        settings = get_settings()
        return SupabaseRestClient(settings.supabase_url, settings.supabase_key)
    except Exception as exc:
        logger.warning("Supabase client unavailable: %s", exc)
        return None


def _persist_instagram_credentials(
    supabase_client: SupabaseRestClient,
    instagram_business_id: str,
    page_id: str,
    page_access_token: str,
    page_name: Optional[str],
    token_data: dict[str, Any],
    subscribed_fields: Optional[str],
    subscribed_result: Optional[dict[str, Any]],
) -> None:
    metadata: dict[str, Any] = {
        "instagram_business_id": instagram_business_id,
        "page_id": page_id,
        "page_name": page_name,
        "page_access_token": page_access_token,
        "token_type": token_data.get("token_type"),
        "expires_in": token_data.get("expires_in"),
    }
    if subscribed_fields:
        metadata["subscribed_fields"] = subscribed_fields
    if subscribed_result is not None:
        metadata["subscribed_result"] = subscribed_result

    existing = supabase_client.get_platform_account("instagram", instagram_business_id)
    if existing:
        update_payload: dict[str, Any] = {
            "platform_metadata": metadata,
            "platform_username": page_name or existing.get("platform_username"),
            "is_verified": True,
        }
        supabase_client.update_platform_account(existing["id"], update_payload)
        return

    user = supabase_client.create_user(
        display_name=page_name or f"Instagram {instagram_business_id}"
    )
    supabase_client.create_platform_account(
        user_id=user["id"],
        platform="instagram",
        platform_user_id=instagram_business_id,
        platform_username=page_name,
        platform_metadata=metadata,
        is_primary=True,
    )


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


async def _verify_supabase_connectivity(client: SupabaseRestClient) -> bool:
    """
    Verify Supabase connectivity by performing a simple query.

    Returns:
        True if connection is successful, False otherwise
    """
    try:
        # Attempt a simple query to verify connectivity
        # This queries the sessions table with a limit of 0 (just checks connectivity)
        client.get_session("00000000-0000-0000-0000-000000000000")
        return True
    except Exception as exc:
        logger.error("Supabase connectivity check failed: %s", exc)
        return False


async def _verify_openai_connectivity(api_key: str, timeout: float = 10.0) -> bool:
    """
    Verify OpenAI API connectivity by listing models.

    Returns:
        True if connection is successful, False otherwise
    """
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, timeout=timeout)
        # Simple API call to verify connectivity
        await client.models.list()
        return True
    except Exception as exc:
        logger.error("OpenAI connectivity check failed: %s", exc)
        return False


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
    app.state.supabase_client = supabase_client

    # Verify Supabase connectivity at startup
    if not await _verify_supabase_connectivity(supabase_client):
        logger.warning(
            "Supabase connectivity check failed at startup - "
            "the service may not function correctly"
        )
    else:
        logger.info("Supabase connectivity verified")

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
        # Verify OpenAI connectivity at startup
        if not await _verify_openai_connectivity(settings.openai.api_key):
            logger.warning(
                "OpenAI connectivity check failed at startup - "
                "agentic workflow may not function correctly"
            )
        else:
            logger.info("OpenAI connectivity verified")

        _agent_orchestrator = AgentOrchestrator(
            openai_api_key=settings.openai.api_key,
            model=settings.openai.model,
            supabase_client=supabase_client,
            timeout=settings.openai.timeout,
            max_retries=settings.openai.max_retries,
        )
        logger.info(
            "Agent orchestrator initialized",
            extra={
                "model": settings.openai.model,
                "timeout": settings.openai.timeout,
            },
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


def _is_truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _redact_payload(data: Any) -> Any:
    """Redact sensitive fields from payloads before logging."""
    sensitive_keys = {
        "access_token",
        "token",
        "authorization",
        "cookie",
        "x-hub-signature-256",
        "signature",
        "secret",
    }

    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if key_lower in sensitive_keys or "token" in key_lower or "secret" in key_lower:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_payload(value)
        return redacted

    if isinstance(data, list):
        return [_redact_payload(item) for item in data[:5]]

    return data


def _summarize_webhook_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return compact payload metadata for observability."""
    entry = data.get("entry", [])
    first_entry = entry[0] if isinstance(entry, list) and entry else {}
    messaging = first_entry.get("messaging", []) if isinstance(first_entry, dict) else []
    changes = first_entry.get("changes", []) if isinstance(first_entry, dict) else []
    first_messaging = messaging[0] if isinstance(messaging, list) and messaging else {}
    first_change = changes[0] if isinstance(changes, list) and changes else {}
    first_change_value = (
        first_change.get("value", {}) if isinstance(first_change, dict) else {}
    )

    return {
        "top_level_keys": sorted(data.keys()),
        "object": data.get("object"),
        "entry_count": len(entry) if isinstance(entry, list) else 0,
        "first_entry_keys": sorted(first_entry.keys()) if isinstance(first_entry, dict) else [],
        "messaging_count": len(messaging) if isinstance(messaging, list) else 0,
        "first_messaging_keys": (
            sorted(first_messaging.keys()) if isinstance(first_messaging, dict) else []
        ),
        "changes_count": len(changes) if isinstance(changes, list) else 0,
        "first_change_field": (
            first_change.get("field") if isinstance(first_change, dict) else None
        ),
        "first_change_value_keys": (
            sorted(first_change_value.keys()) if isinstance(first_change_value, dict) else []
        ),
    }


def _require_facebook_settings() -> tuple[Any, Any]:
    settings = get_settings()
    if not settings.facebook:
        raise HTTPException(status_code=501, detail="Facebook OAuth not configured")
    return settings, settings.facebook


class FacebookSubscribeRequest(BaseModel):
    page_id: str
    page_access_token: str
    subscribed_fields: str = "messages"


@app.get("/auth/facebook/login")
async def facebook_login(request: Request) -> RedirectResponse:
    """
    Redirect the user to Facebook OAuth login.

    Sets a state cookie for CSRF protection.
    """
    settings, facebook = _require_facebook_settings()

    state = secrets.token_urlsafe(24)

    return_to = request.query_params.get("return_to")
    requested_page_id = request.query_params.get("page_id")
    subscribe = _is_truthy(request.query_params.get("subscribe"))
    persist = _is_truthy(request.query_params.get("persist"))
    include_page_tokens = _is_truthy(request.query_params.get("include_page_tokens"))
    subscribed_fields = request.query_params.get("subscribed_fields", "messages")

    if return_to and not _is_allowed_return_url(return_to, facebook.allowed_return_urls):
        raise HTTPException(status_code=400, detail="Invalid return_to URL")

    oauth_url = build_oauth_url(
        app_id=facebook.app_id,
        redirect_uri=facebook.redirect_uri,
        state=state,
        scopes=facebook.login_scopes,
        graph_api_version=facebook.graph_api_version,
    )

    response = RedirectResponse(oauth_url, status_code=302)
    response.set_cookie(
        FACEBOOK_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    response.set_cookie(
        FACEBOOK_FLOW_COOKIE,
        json.dumps(
            {
                "return_to": return_to,
                "page_id": requested_page_id,
                "subscribe": subscribe,
                "persist": persist,
                "include_page_tokens": include_page_tokens,
                "subscribed_fields": subscribed_fields,
            }
        ),
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    return response


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request) -> JSONResponse:
    """
    Handle Facebook OAuth callback and return tokens/page info.

    Optional query params:
    - page_id: select a specific page
    - subscribe: true/false to call /subscribed_apps
    - persist: true/false to store page tokens for Instagram replies
    - subscribed_fields: comma-separated fields (default: messages)
    - include_page_tokens: true/false to include page access tokens in response
    """
    settings, facebook = _require_facebook_settings()

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    cookie_state = request.cookies.get(FACEBOOK_STATE_COOKIE)

    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    flow_cookie_raw = request.cookies.get(FACEBOOK_FLOW_COOKIE)
    flow_cookie: dict[str, Any] = {}
    if flow_cookie_raw:
        try:
            parsed_cookie = json.loads(flow_cookie_raw)
            if isinstance(parsed_cookie, dict):
                flow_cookie = parsed_cookie
        except json.JSONDecodeError:
            flow_cookie = {}

    page_id = request.query_params.get("page_id") or flow_cookie.get("page_id")
    subscribe = _is_truthy(
        request.query_params.get("subscribe")
        if request.query_params.get("subscribe") is not None
        else str(flow_cookie.get("subscribe", "false"))
    )
    persist = _is_truthy(
        request.query_params.get("persist")
        if request.query_params.get("persist") is not None
        else str(flow_cookie.get("persist", "false"))
    )
    subscribed_fields = request.query_params.get("subscribed_fields") or str(
        flow_cookie.get("subscribed_fields", "messages")
    )
    include_page_tokens = _is_truthy(
        request.query_params.get("include_page_tokens")
        if request.query_params.get("include_page_tokens") is not None
        else str(flow_cookie.get("include_page_tokens", "false"))
    )
    return_to = flow_cookie.get("return_to")

    if subscribe and not page_id:
        raise HTTPException(status_code=400, detail="subscribe=true requires page_id")

    persisted = False
    persist_error: Optional[str] = None

    async with FacebookGraphClient(
        app_id=facebook.app_id,
        app_secret=facebook.app_secret,
        graph_api_version=facebook.graph_api_version,
    ) as client:
        token_data = await client.exchange_code_for_user_token(
            code=code,
            redirect_uri=facebook.redirect_uri,
        )

        user_access_token = token_data.get("access_token")
        if not user_access_token:
            raise HTTPException(status_code=502, detail="Access token missing in response")

        pages = await client.get_pages(user_access_token)

        selected_page = None
        if page_id:
            for page in pages:
                if page.id == str(page_id):
                    selected_page = page
                    break
            if not selected_page:
                raise HTTPException(status_code=404, detail="Page not found for user")
        elif pages:
            selected_page = pages[0]

        instagram_business_id = None
        subscribed_result = None

        if selected_page and selected_page.access_token:
            instagram_business_id = await client.get_instagram_business_id(
                page_id=selected_page.id,
                page_access_token=selected_page.access_token,
            )

            if subscribe:
                subscribed_result = await client.subscribe_page(
                    page_id=selected_page.id,
                    page_access_token=selected_page.access_token,
                    subscribed_fields=subscribed_fields,
                )
            if persist:
                if not instagram_business_id:
                    persist_error = "Instagram business ID not found for selected page"
                else:
                    supabase_client = _get_supabase_client()
                    if not supabase_client:
                        persist_error = "Supabase client not available"
                    else:
                        try:
                            _persist_instagram_credentials(
                                supabase_client=supabase_client,
                                instagram_business_id=str(instagram_business_id),
                                page_id=str(selected_page.id),
                                page_access_token=str(selected_page.access_token),
                                page_name=selected_page.name,
                                token_data=token_data,
                                subscribed_fields=subscribed_fields if subscribe else None,
                                subscribed_result=subscribed_result,
                            )
                            persisted = True
                        except Exception as exc:
                            persist_error = str(exc)
                            logger.exception(
                                "Failed to persist Instagram credentials for page %s",
                                selected_page.id,
                            )
        elif subscribe:
            raise HTTPException(
                status_code=400,
                detail="Selected page is missing an access token",
            )

        response_pages = [page.to_dict(include_page_tokens) for page in pages]
        response_payload = {
            "user_access_token": user_access_token,
            "expires_in": token_data.get("expires_in"),
            "token_type": token_data.get("token_type"),
            "pages": response_pages,
            "selected_page_id": selected_page.id if selected_page else None,
            "instagram_business_id": instagram_business_id,
            "subscribed_fields": subscribed_fields if subscribe else None,
            "subscribed_result": subscribed_result,
            "persisted": persisted,
            "persist_error": persist_error,
        }

    if return_to and _is_allowed_return_url(str(return_to), facebook.allowed_return_urls):
        redirect_url = _safe_redirect_with_query(
            str(return_to),
            _build_callback_payload(response_payload, include_page_tokens),
        )
        response = RedirectResponse(redirect_url, status_code=302)
    else:
        response = JSONResponse(response_payload)

    response.delete_cookie(FACEBOOK_STATE_COOKIE)
    response.delete_cookie(FACEBOOK_FLOW_COOKIE)
    return response


@app.post("/auth/facebook/subscribe")
async def facebook_subscribe(payload: FacebookSubscribeRequest) -> dict[str, Any]:
    """Subscribe a Page to the app using a Page access token."""
    _, facebook = _require_facebook_settings()

    async with FacebookGraphClient(
        app_id=facebook.app_id,
        app_secret=facebook.app_secret,
        graph_api_version=facebook.graph_api_version,
    ) as client:
        return await client.subscribe_page(
            page_id=payload.page_id,
            page_access_token=payload.page_access_token,
            subscribed_fields=payload.subscribed_fields,
        )


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
            # Also creates/links User and PlatformAccount for this Telegram user
            session, is_new_session = supabase_client.get_or_create_active_session(
                platform="telegram",
                platform_user_id=incoming.user.platform_user_id,
                platform_chat_id=int(incoming.chat.platform_chat_id) if incoming.chat.platform_chat_id else None,
                metadata={
                    "username": incoming.user.username,
                    "display_name": incoming.user.display_name,
                },
                # User linking parameters
                platform_username=incoming.user.username,
                display_name=incoming.user.display_name,
                platform_metadata={
                    "first_name": incoming.user.first_name,
                    "last_name": incoming.user.last_name,
                    "language_code": incoming.user.language_code,
                } if incoming.user.first_name else None,
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
        enabled_override=settings.debug_reporter_enabled,
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
    platform_event_summary: dict[str, Any] = {}
    summarize_events = getattr(adapter, "summarize_webhook_events", None)
    if callable(summarize_events):
        try:
            platform_event_summary = summarize_events(data)
        except Exception as exc:
            logger.debug(
                "Failed to summarize webhook events",
                extra={"platform": platform.value, "error": str(exc)},
            )

    parse_many = getattr(adapter, "parse_incoming_many", None)
    if callable(parse_many):
        incoming_messages = parse_many(data)
    else:
        single_incoming = adapter.parse_incoming(data)
        incoming_messages = [single_incoming] if single_incoming else []

    if not incoming_messages:
        message = "Webhook payload contained non-message events"
        if platform_event_summary.get("event_type_counts"):
            message = "Webhook payload had no processable user message"
        logger.debug(
            message,
            extra={
                "platform": platform.value,
                "payload_summary": _summarize_webhook_payload(data),
                "event_summary": platform_event_summary,
            },
        )
        return {"status": "ok", "processed": False}

    processed_count = 0
    response_sent_count = 0
    response_errors: list[str] = []
    last_content_type: Optional[str] = None

    for incoming in incoming_messages:
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
            enabled_override=settings.debug_reporter_enabled,
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
            processed_count += 1
            last_content_type = result.content_type.value
            logger.info(
                "Agent processed message",
                extra={
                    "platform": platform.value,
                    "handler": result.handler_name,
                    "content_type": result.content_type.value,
                    "success": result.success,
                },
            )

            # Send handler response back to the originating chat for non-Telegram webhooks.
            # Telegram has its own update handler path, but this unified webhook path
            # should mirror the same "process + reply" behavior for Instagram/TikTok.
            if result.message:
                outbound_text = result.message
                if platform != Platform.TELEGRAM:
                    # Non-Telegram platforms do not support Telegram HTML parse modes.
                    outbound_text = re.sub(r"<br\\s*/?>", "\n", outbound_text, flags=re.IGNORECASE)
                    outbound_text = re.sub(r"</p\\s*>", "\n\n", outbound_text, flags=re.IGNORECASE)
                    outbound_text = re.sub(r"<[^>]+>", "", outbound_text).strip()

                if not outbound_text.strip():
                    response_errors.append("Skipping empty response after formatting")
                    logger.warning(
                        "Skipping empty platform response",
                        extra={
                            "platform": platform.value,
                            "chat_id": incoming.chat.platform_chat_id,
                        },
                    )
                else:
                    outbound_metadata: dict[str, Any] = {}
                    if platform == Platform.INSTAGRAM:
                        recipient_id = incoming.chat.metadata.get("recipient_id")
                        if not recipient_id or not str(recipient_id).isdigit():
                            response_errors.append(
                                "Missing instagram_account_id from webhook recipient.id"
                            )
                            logger.error(
                                "Missing or invalid Instagram recipient_id in webhook payload",
                                extra={
                                    "platform": platform.value,
                                    "chat_id": incoming.chat.platform_chat_id,
                                },
                            )
                        else:
                            outbound_metadata["instagram_account_id"] = str(recipient_id)

                    if platform != Platform.INSTAGRAM or outbound_metadata.get("instagram_account_id"):
                        delivery = await adapter.send_message(
                            OutgoingMessage(
                                chat_id=incoming.chat.platform_chat_id,
                                text=outbound_text,
                                platform=platform,
                                metadata=outbound_metadata,
                            )
                        )

                        if delivery.success:
                            response_sent_count += 1
                        elif delivery.error:
                            response_errors.append(delivery.error)
                            logger.error(
                                "Failed sending platform response",
                                extra={
                                    "platform": platform.value,
                                    "chat_id": incoming.chat.platform_chat_id,
                                    "error": delivery.error,
                                },
                            )

            # Flush debug logs to user in dev mode
            if debug_reporter.enabled:
                await debug_reporter.flush()

            continue

        # No orchestrator - just send debug info if in dev mode
        if debug_reporter.enabled:
            debug_reporter.warn("Agent orchestrator not available")
            debug_reporter.info("Message echo", data={"text": incoming.text})
            await debug_reporter.flush()

    if processed_count == 0:
        logger.debug("Agent orchestrator not available, skipping processing")
        return {"status": "ok", "processed": False}

    return {
        "status": "ok",
        "processed": True,
        "processed_count": processed_count,
        "content_type": last_content_type,
        "response_sent": response_sent_count > 0,
        "response_sent_count": response_sent_count,
        "response_error": response_errors[0] if response_errors else None,
        "response_errors": response_errors,
    }


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
    # Use dedicated verify token when available, fallback to app secret
    if not settings.instagram or not (
        settings.instagram.verify_token or settings.instagram.app_secret
    ):
        logger.error("Instagram webhook verification failed: verify token not configured")
        raise HTTPException(
            status_code=501,
            detail="Instagram webhook verification not configured"
        )

    verify_token = settings.instagram.verify_token or settings.instagram.app_secret

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
        payload_summary = _summarize_webhook_payload(data)
        logger.debug("Instagram webhook payload summary", extra=payload_summary)

        summarize_events = getattr(adapter, "summarize_webhook_events", None)
        if callable(summarize_events):
            try:
                logger.debug(
                    "Instagram webhook event summary",
                    extra=summarize_events(data),
                )
            except Exception as exc:
                logger.debug(
                    "Instagram webhook event summary unavailable",
                    extra={"error": str(exc)},
                )

        if _is_truthy(os.getenv("LOG_WEBHOOK_PAYLOADS")):
            logger.debug(
                "Instagram webhook payload (redacted)",
                extra={"payload": _redact_payload(data)},
            )

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
