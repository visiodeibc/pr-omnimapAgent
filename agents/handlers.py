"""
Handler functions for each content type.

Each handler is responsible for processing a specific type of classified content
and returning a HandlerResult. These are stub implementations that log the
processing and will be filled in with actual logic.
"""

from typing import Any, Dict, Optional

from openai import AsyncOpenAI

from agents.types import (
    ContentType,
    ExtractedData,
    HandlerResult,
    UnifiedRequest,
    build_conversation_response_prompt,
)
from logging_config import get_logger
from services.google_places import GooglePlacesService, PlaceSearchQuery
from services.instagram_graph import (
    InstagramGraphService,
    canonicalize_permalink,
)
from services.memory import ConversationContext, MemoryService
from settings import get_settings

logger = get_logger(__name__)


async def handle_place_name(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Handle messages classified as containing a place name.

    This handler will:
    1. Search for the place in Google Places API
    2. Return place details with Google Maps links
    3. Queue follow-up jobs for enrichment (future)

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

    Returns:
        HandlerResult with processing outcome
    """
    logger.info(
        "📍 [PLACE_NAME] Processing place name request",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "place_name": extracted.place_name,
            "location_hints": extracted.location_hints,
            "confidence": extracted.confidence,
            "session_id": session_id,
        },
    )

    # Check if Google Places API is configured
    settings = get_settings()
    if not settings.google_places_enabled:
        logger.warning(
            "Google Places API not configured, returning stub response",
            extra={"place_name": extracted.place_name},
        )
        return HandlerResult(
            success=False,
            handler_name="handle_place_name",
            content_type=ContentType.PLACE_NAME,
            data={
                "place_name": extracted.place_name,
                "location_hints": extracted.location_hints,
                "status": "not_configured",
            },
            error="Google Places API key not configured",
            error_code="GOOGLE_PLACES_NOT_CONFIGURED",
            message="Place search is not available. Please configure GOOGLE_MAPS_API_KEY.",
        )

    # Build search query with location hints
    location_hint = None
    if extracted.location_hints:
        location_hint = ", ".join(extracted.location_hints)

    query = PlaceSearchQuery(
        query=extracted.place_name or "",
        location_hint=location_hint,
    )

    # Search Google Places using async context manager for guaranteed cleanup
    async with GooglePlacesService(api_key=settings.google_places.api_key) as service:
        try:
            results = await service.search_place(query)

            if not results:
                logger.info(
                    "No places found for query",
                    extra={"place_name": extracted.place_name},
                )
                return HandlerResult(
                    success=True,
                    handler_name="handle_place_name",
                    content_type=ContentType.PLACE_NAME,
                    data={
                        "place_name": extracted.place_name,
                        "location_hints": extracted.location_hints,
                        "search_results": [],
                        "status": "not_found",
                    },
                    message=f"No places found for '{extracted.place_name}'.",
                    follow_up_actions=["search_osm"],
                )

            # Convert results to serializable format
            search_results = [result.to_dict() for result in results]

            logger.info(
                "Place search completed successfully",
                extra={
                    "place_name": extracted.place_name,
                    "results_count": len(search_results),
                },
            )

            # Build response message with results (HTML formatting for Telegram)
            # Show up to 5 results
            results_to_show = results[:5]
            message = f"Found {len(results)} result(s) for '{extracted.place_name}'.\n"

            for i, result in enumerate(results_to_show, start=1):
                message += f"\n<b>{i}. {result.name}</b>\n"
                message += f"📍 {result.formatted_address}\n"
                if result.rating:
                    message += f"⭐ {result.rating}"
                    if result.user_ratings_total:
                        message += f" ({result.user_ratings_total} reviews)"
                    message += "\n"
                message += f"🔗 {result.google_maps_url}\n"

            return HandlerResult(
                success=True,
                handler_name="handle_place_name",
                content_type=ContentType.PLACE_NAME,
                data={
                    "place_name": extracted.place_name,
                    "location_hints": extracted.location_hints,
                    "search_results": search_results,
                    "status": "found",
                },
                message=message,
                follow_up_actions=["enrich_place_data", "store_candidate"],
            )

        except Exception as e:
            logger.error(
                "Google Places search failed",
                extra={
                    "place_name": extracted.place_name,
                    "error": str(e),
                },
            )
            return HandlerResult(
                success=False,
                handler_name="handle_place_name",
                content_type=ContentType.PLACE_NAME,
                data={
                    "place_name": extracted.place_name,
                    "location_hints": extracted.location_hints,
                    "status": "error",
                },
                error=str(e),
                error_code="GOOGLE_PLACES_ERROR",
                message=f"Failed to search for '{extracted.place_name}'. Please try again later.",
            )


async def handle_conversation(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
    conversation_context: Optional[ConversationContext] = None,
    memory_service: Optional[MemoryService] = None,
) -> HandlerResult:
    """
    Handle conversation messages (questions, greetings, general chat).

    This handler will:
    1. Load conversation context from memory
    2. Generate a context-aware response using OpenAI
    3. Return a helpful, conversational response

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context
        conversation_context: Optional conversation context from memory
        memory_service: Optional memory service for building context strings

    Returns:
        HandlerResult with processing outcome
    """
    logger.info(
        "💬 [CONVERSATION] Processing conversation message",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "message_text": extracted.message_text,
            "topic": extracted.message_topic,
            "intent": extracted.message_intent,
            "confidence": extracted.confidence,
            "session_id": session_id,
            "has_context": conversation_context.has_context() if conversation_context else False,
        },
    )

    # Get settings to check if OpenAI is available
    settings = get_settings()
    if not settings.agent_enabled:
        logger.warning("OpenAI not configured, returning default response")
        return HandlerResult(
            success=True,
            handler_name="handle_conversation",
            content_type=ContentType.CONVERSATION,
            data={
                "message_text": extracted.message_text,
                "topic": extracted.message_topic,
                "intent": extracted.message_intent,
                "status": "openai_not_configured",
            },
            message="Hi! I'm OmniMap. I can help you discover places from Instagram and TikTok links, or search for specific locations. Send me a link or a place name to get started!",
            follow_up_actions=["await_user_input"],
        )

    # Build conversation context string for the prompt
    context_string = ""
    if conversation_context and memory_service and conversation_context.has_context():
        context_string = memory_service.build_prompt_context(conversation_context)
        logger.debug(
            "Built conversation context for response",
            extra={"context_message_count": conversation_context.message_count},
        )

    # Build the system prompt with or without context
    system_prompt = build_conversation_response_prompt(
        context_string,
        platform=request.platform,
    )

    # Generate contextual response using OpenAI
    try:
        openai_client = AsyncOpenAI(
            api_key=settings.openai.api_key,
            timeout=settings.openai.timeout,
            max_retries=settings.openai.max_retries,
        )
        response = await openai_client.chat.completions.create(
            model=settings.openai.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.raw_content or ""},
            ],
            max_tokens=1024,
            temperature=0.7,
        )

        ai_response = response.choices[0].message.content or ""

        logger.info(
            "Generated contextual response for conversation",
            extra={
                "response_preview": ai_response[:100] if ai_response else None,
                "had_context": bool(context_string),
                "topic": extracted.message_topic,
            },
        )

        return HandlerResult(
            success=True,
            handler_name="handle_conversation",
            content_type=ContentType.CONVERSATION,
            data={
                "message_text": extracted.message_text,
                "topic": extracted.message_topic,
                "intent": extracted.message_intent,
                "status": "responded",
                "had_conversation_context": bool(context_string),
            },
            message=ai_response,
            follow_up_actions=["continue_conversation"],
        )

    except TimeoutError as e:
        logger.warning(
            "OpenAI request timed out",
            extra={"error": str(e)},
        )
        return HandlerResult(
            success=False,
            handler_name="handle_conversation",
            content_type=ContentType.CONVERSATION,
            data={
                "message_text": extracted.message_text,
                "topic": extracted.message_topic,
                "intent": extracted.message_intent,
                "status": "timeout_error",
            },
            error="Request timed out",
            error_code="TIMEOUT",
            message="I'm experiencing some delays. Please try again in a moment.",
            follow_up_actions=["await_user_input"],
        )
    except Exception as e:
        logger.error(
            "Failed to generate contextual response",
            extra={"error": str(e), "error_type": type(e).__name__},
        )
        return HandlerResult(
            success=True,  # Return True so user gets a response
            handler_name="handle_conversation",
            content_type=ContentType.CONVERSATION,
            data={
                "message_text": extracted.message_text,
                "topic": extracted.message_topic,
                "intent": extracted.message_intent,
                "status": "fallback_response",
            },
            message="Hi! I'm OmniMap. I can help you discover places from Instagram and TikTok links, or search for specific locations. Send me a link or a place name to get started!",
            follow_up_actions=["await_user_input"],
        )


def _resolve_instagram_target(
    request: UnifiedRequest, extracted: ExtractedData
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Pick the best IG URL to fetch metadata for.

    Prefers a canonical permalink from a DM share attachment (set by the IG
    adapter when the user shares a reel/post), falling back to whatever the
    classifier extracted from text.
    """
    share = None
    if isinstance(request.metadata, dict):
        share = request.metadata.get("instagram_share")

    candidates: list[str] = []
    if isinstance(share, dict):
        for key in ("url", "reel_video_url"):
            value = share.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
    if extracted.url:
        candidates.append(extracted.url)
    if request.raw_content:
        candidates.append(request.raw_content)

    for candidate in candidates:
        permalink = canonicalize_permalink(candidate)
        if permalink:
            return permalink, share if isinstance(share, dict) else None

    return None, share if isinstance(share, dict) else None


async def _summarize_instagram_post(
    post_info: Any,
    settings: Any,
) -> Optional[str]:
    """Ask the LLM to summarize the IG post given its public metadata."""
    if not settings.agent_enabled:
        return None

    title = (post_info.title or "").strip()
    author = post_info.author_name or "unknown"
    media_label = {"reel": "reel", "post": "post", "tv": "IGTV video"}.get(
        post_info.media_type or "", "post"
    )

    user_content = (
        f"Author: @{author}\n"
        f"Type: Instagram {media_label}\n"
        f"Permalink: {post_info.permalink}\n"
        f"Caption: {title or '(no caption returned by oEmbed)'}\n"
    )

    system_prompt = (
        "You are OmniMap. The user shared an Instagram post or reel. "
        "Write a short, friendly summary (2-4 sentences) of what the post is "
        "about based on the caption and author. If the caption is empty or "
        "uninformative, say so briefly and suggest the user open the link. "
        "If any place names appear, list them on a final line prefixed with "
        "'Places mentioned:'. Do not invent details that are not in the caption."
    )

    try:
        client = AsyncOpenAI(
            api_key=settings.openai.api_key,
            timeout=settings.openai.timeout,
            max_retries=settings.openai.max_retries,
        )
        response = await client.chat.completions.create(
            model=settings.openai.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=400,
            temperature=0.4,
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as exc:
        logger.warning(
            "OpenAI summary for Instagram post failed",
            extra={"error": str(exc), "permalink": post_info.permalink},
        )
        return None


async def handle_instagram_link(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """Fetch Instagram post/reel metadata and reply with a summary."""
    permalink, share = _resolve_instagram_target(request, extracted)

    logger.info(
        "📸 [INSTAGRAM_LINK] Processing Instagram link request",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "url": extracted.url,
            "permalink": permalink,
            "is_dm_share": bool(share),
            "share_type": (share or {}).get("type"),
            "confidence": extracted.confidence,
            "session_id": session_id,
        },
    )

    settings = get_settings()
    instagram_settings = settings.instagram
    facebook_settings = settings.facebook

    app_id = facebook_settings.app_id if facebook_settings else None
    app_secret = (
        facebook_settings.app_secret
        if facebook_settings
        else (instagram_settings.app_secret if instagram_settings else None)
    )
    access_token = instagram_settings.access_token if instagram_settings else None
    ig_user_id = instagram_settings.account_id if instagram_settings else None

    if not (access_token or (app_id and app_secret)):
        logger.warning(
            "Instagram Graph credentials missing; cannot fetch post metadata"
        )
        return HandlerResult(
            success=False,
            handler_name="handle_instagram_link",
            content_type=ContentType.INSTAGRAM_LINK,
            data={"url": extracted.url, "status": "not_configured"},
            error="Instagram Graph credentials not configured",
            error_code="INSTAGRAM_GRAPH_NOT_CONFIGURED",
            message=(
                "I received an Instagram link, but I'm not configured to fetch "
                "Instagram metadata. Please set INSTAGRAM_ACCESS_TOKEN or "
                "FACEBOOK_APP_ID/FACEBOOK_APP_SECRET."
            ),
        )

    if not permalink:
        logger.info(
            "No canonical Instagram permalink could be resolved",
            extra={"url": extracted.url, "share_type": (share or {}).get("type")},
        )
        return HandlerResult(
            success=True,
            handler_name="handle_instagram_link",
            content_type=ContentType.INSTAGRAM_LINK,
            data={
                "url": extracted.url,
                "share": share,
                "status": "no_permalink",
            },
            message=(
                "I couldn't extract a public Instagram permalink from this "
                "share. If it was a story or a private post, I can't fetch it."
            ),
        )

    async with InstagramGraphService(
        app_id=app_id,
        app_secret=app_secret,
        access_token=access_token,
        ig_user_id=ig_user_id,
    ) as service:
        try:
            post_info = await service.fetch_post_info(permalink)
        except Exception as exc:
            logger.error(
                "Failed to fetch Instagram post metadata",
                extra={"permalink": permalink, "error": str(exc)},
            )
            return HandlerResult(
                success=False,
                handler_name="handle_instagram_link",
                content_type=ContentType.INSTAGRAM_LINK,
                data={"url": extracted.url, "permalink": permalink, "status": "error"},
                error=str(exc),
                error_code="INSTAGRAM_GRAPH_ERROR",
                message=(
                    "I couldn't fetch this Instagram post. It may be private, "
                    "removed, or not yet propagated. Try again in a moment."
                ),
            )

    if not post_info:
        return HandlerResult(
            success=True,
            handler_name="handle_instagram_link",
            content_type=ContentType.INSTAGRAM_LINK,
            data={"url": extracted.url, "permalink": permalink, "status": "no_data"},
            message=(
                "Instagram didn't return any public info for this link. It may "
                "be a private or restricted post."
            ),
        )

    summary = await _summarize_instagram_post(post_info, settings)

    if summary:
        message = (
            f"📸 Instagram {post_info.media_type or 'post'} by "
            f"@{post_info.author_name or 'unknown'}\n\n"
            f"{summary}\n\n"
            f"🔗 {post_info.permalink}"
        )
    else:
        caption_preview = (post_info.title or "").strip()
        if len(caption_preview) > 400:
            caption_preview = caption_preview[:400].rstrip() + "..."
        message = (
            f"📸 Instagram {post_info.media_type or 'post'} by "
            f"@{post_info.author_name or 'unknown'}\n\n"
            f"{caption_preview or '(no caption available)'}\n\n"
            f"🔗 {post_info.permalink}"
        )

    return HandlerResult(
        success=True,
        handler_name="handle_instagram_link",
        content_type=ContentType.INSTAGRAM_LINK,
        data={
            "url": extracted.url,
            "permalink": post_info.permalink,
            "shortcode": post_info.shortcode,
            "author_name": post_info.author_name,
            "media_type": post_info.media_type,
            "share": share,
            "status": "summarized",
            "summary_via_llm": bool(summary),
        },
        message=message,
        follow_up_actions=["extract_places_from_caption"],
    )


async def handle_tiktok_link(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Handle messages containing TikTok links.

    This handler will:
    1. Fetch the TikTok video content
    2. Extract place mentions from description
    3. Process any location information
    4. Queue place extraction jobs

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

    Returns:
        HandlerResult with processing outcome
    """
    logger.info(
        "🎵 [TIKTOK_LINK] Processing TikTok link request",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "url": extracted.url,
            "video_id": extracted.link_content_id,
            "tiktok_username": extracted.link_username,
            "confidence": extracted.confidence,
            "session_id": session_id,
        },
    )

    # NOTE: This is a stub implementation - TikTok link processing not yet implemented
    # Future implementation will:
    # 1. Fetch TikTok video metadata via API
    # 2. Extract description text
    # 3. Extract location information
    # 4. Process hashtags for place hints
    # 5. Queue place extraction jobs

    logger.warning(
        "TikTok link handler not yet implemented",
        extra={"url": extracted.url, "video_id": extracted.link_content_id},
    )

    return HandlerResult(
        success=False,
        handler_name="handle_tiktok_link",
        content_type=ContentType.TIKTOK_LINK,
        data={
            "url": extracted.url,
            "video_id": extracted.link_content_id,
            "tiktok_username": extracted.link_username,
            "status": "not_implemented",
        },
        error="TikTok link processing not yet implemented",
        error_code="NOT_IMPLEMENTED",
        message="TikTok video link received. This feature is coming soon!",
        follow_up_actions=[
            "fetch_tiktok_content",
            "extract_location_info",
            "extract_places_from_description",
        ],
    )


async def handle_other_link(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Handle messages containing non-Instagram/TikTok links.

    This handler will:
    1. Analyze the link domain
    2. Attempt to extract relevant content
    3. Determine if it contains place information
    4. Route to appropriate processor

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

    Returns:
        HandlerResult with processing outcome
    """
    logger.info(
        "🔗 [OTHER_LINK] Processing other link request",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "url": extracted.url,
            "domain": extracted.link_domain,
            "confidence": extracted.confidence,
            "session_id": session_id,
        },
    )

    # NOTE: This is a stub implementation - generic link processing not yet implemented
    # Future implementation will:
    # 1. Fetch link content/metadata
    # 2. Determine content type (article, map, business listing, etc.)
    # 3. Extract relevant place information
    # 4. Route to specialized processor based on domain

    logger.warning(
        "Other link handler not yet implemented",
        extra={"url": extracted.url, "domain": extracted.link_domain},
    )

    return HandlerResult(
        success=False,
        handler_name="handle_other_link",
        content_type=ContentType.OTHER_LINK,
        data={
            "url": extracted.url,
            "domain": extracted.link_domain,
            "status": "not_implemented",
        },
        error="Generic link processing not yet implemented",
        error_code="NOT_IMPLEMENTED",
        message=f"Link from {extracted.link_domain} received. This feature is coming soon!",
        follow_up_actions=["fetch_link_metadata", "analyze_content", "extract_places"],
    )


# Handler registry for dynamic dispatch
HANDLER_REGISTRY = {
    ContentType.PLACE_NAME: handle_place_name,
    ContentType.CONVERSATION: handle_conversation,
    ContentType.INSTAGRAM_LINK: handle_instagram_link,
    ContentType.TIKTOK_LINK: handle_tiktok_link,
    ContentType.OTHER_LINK: handle_other_link,
}


async def dispatch_handler(
    content_type: ContentType,
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
    conversation_context: Optional[ConversationContext] = None,
    memory_service: Optional[MemoryService] = None,
) -> HandlerResult:
    """
    Dispatch to the appropriate handler based on content type.

    Args:
        content_type: The classified content type
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context
        conversation_context: Optional conversation context for handlers that need it
        memory_service: Optional memory service for context building

    Returns:
        HandlerResult from the appropriate handler
    """
    handler = HANDLER_REGISTRY.get(content_type)
    if not handler:
        logger.error(
            "No handler registered for content type",
            extra={"content_type": content_type.value},
        )
        return HandlerResult(
            success=False,
            handler_name="dispatch_handler",
            content_type=content_type,
            error=f"No handler for content type: {content_type.value}",
            error_code="NO_HANDLER",
        )

    # Pass additional context to handlers that support it
    if content_type == ContentType.CONVERSATION:
        return await handler(
            request,
            extracted,
            session_id,
            conversation_context=conversation_context,
            memory_service=memory_service,
        )

    return await handler(request, extracted, session_id)
