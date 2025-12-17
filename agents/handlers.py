"""
Handler functions for each content type.

Each handler is responsible for processing a specific type of classified content
and returning a HandlerResult. These are stub implementations that log the
processing and will be filled in with actual logic.
"""

from typing import Optional

from agents.types import ContentType, ExtractedData, HandlerResult, UnifiedRequest
from logging_config import get_logger
from services.google_places import GooglePlacesService, PlaceSearchQuery
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

    # Search Google Places
    service = GooglePlacesService(api_key=settings.google_places.api_key)
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

        # Build response message with top result (HTML formatting for Telegram)
        top_result = results[0]
        message = (
            f"Found {len(results)} result(s) for '{extracted.place_name}'.\n\n"
            f"<b>{top_result.name}</b>\n"
            f"📍 {top_result.formatted_address}\n"
        )
        if top_result.rating:
            message += f"⭐ {top_result.rating}"
            if top_result.user_ratings_total:
                message += f" ({top_result.user_ratings_total} reviews)"
            message += "\n"
        message += f"🔗 {top_result.google_maps_url}"

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
    finally:
        await service.close()


async def handle_question(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Handle messages classified as questions.

    This handler will:
    1. Analyze the question intent
    2. Route to appropriate knowledge source
    3. Generate a response using conversation context
    4. Queue response delivery job

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

    Returns:
        HandlerResult with processing outcome
    """
    logger.info(
        "❓ [QUESTION] Processing question request",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "question_text": extracted.question_text,
            "topic": extracted.question_topic,
            "intent": extracted.question_intent,
            "confidence": extracted.confidence,
            "session_id": session_id,
        },
    )

    # TODO: Implement actual question handling
    # 1. Retrieve session context/memory
    # 2. Determine if question is about a place, usage, or general
    # 3. Query relevant knowledge sources
    # 4. Generate response with LLM
    # 5. Queue response delivery

    logger.debug(
        "Question handler completed (stub implementation)",
        extra={"question_topic": extracted.question_topic},
    )

    return HandlerResult(
        success=True,
        handler_name="handle_question",
        content_type=ContentType.QUESTION,
        data={
            "question_text": extracted.question_text,
            "topic": extracted.question_topic,
            "intent": extracted.question_intent,
            "status": "pending_implementation",
        },
        message="Question received. Response generation will be implemented.",
        follow_up_actions=["retrieve_context", "generate_response", "deliver_response"],
    )


async def handle_instagram_link(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Handle messages containing Instagram links.

    This handler will:
    1. Fetch the Instagram post/reel content
    2. Extract place mentions from caption/comments
    3. Process any location tags
    4. Queue place extraction jobs

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

    Returns:
        HandlerResult with processing outcome
    """
    logger.info(
        "📸 [INSTAGRAM_LINK] Processing Instagram link request",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "url": extracted.url,
            "content_id": extracted.link_content_id,
            "ig_username": extracted.link_username,
            "link_type": extracted.link_type,
            "confidence": extracted.confidence,
            "session_id": session_id,
        },
    )

    # TODO: Implement actual Instagram link processing
    # 1. Fetch Instagram content via API or scraping
    # 2. Extract caption text
    # 3. Extract location tags
    # 4. Extract place mentions from caption
    # 5. Process comments for additional context
    # 6. Queue place extraction jobs

    logger.debug(
        "Instagram link handler completed (stub implementation)",
        extra={"url": extracted.url, "content_type": extracted.link_type},
    )

    return HandlerResult(
        success=True,
        handler_name="handle_instagram_link",
        content_type=ContentType.INSTAGRAM_LINK,
        data={
            "url": extracted.url,
            "content_id": extracted.link_content_id,
            "ig_username": extracted.link_username,
            "link_type": extracted.link_type,
            "status": "pending_implementation",
        },
        message=f"Instagram {extracted.link_type or 'content'} link received. Content extraction will be implemented.",
        follow_up_actions=[
            "fetch_instagram_content",
            "extract_location_tags",
            "extract_places_from_caption",
        ],
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

    # TODO: Implement actual TikTok link processing
    # 1. Fetch TikTok video metadata via API
    # 2. Extract description text
    # 3. Extract location information
    # 4. Process hashtags for place hints
    # 5. Queue place extraction jobs

    logger.debug(
        "TikTok link handler completed (stub implementation)",
        extra={"url": extracted.url, "video_id": extracted.link_content_id},
    )

    return HandlerResult(
        success=True,
        handler_name="handle_tiktok_link",
        content_type=ContentType.TIKTOK_LINK,
        data={
            "url": extracted.url,
            "video_id": extracted.link_content_id,
            "tiktok_username": extracted.link_username,
            "status": "pending_implementation",
        },
        message="TikTok video link received. Content extraction will be implemented.",
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

    # TODO: Implement other link processing
    # 1. Fetch link content/metadata
    # 2. Determine content type (article, map, business listing, etc.)
    # 3. Extract relevant place information
    # 4. Route to specialized processor based on domain

    logger.debug(
        "Other link handler completed (stub implementation)",
        extra={"url": extracted.url, "domain": extracted.link_domain},
    )

    return HandlerResult(
        success=True,
        handler_name="handle_other_link",
        content_type=ContentType.OTHER_LINK,
        data={
            "url": extracted.url,
            "domain": extracted.link_domain,
            "status": "pending_implementation",
        },
        message=f"Link from {extracted.link_domain} received. Content analysis will be implemented.",
        follow_up_actions=["fetch_link_metadata", "analyze_content", "extract_places"],
    )


async def handle_unknown(
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Handle messages that could not be classified.

    This handler will:
    1. Log the unclassified message for analysis
    2. Attempt fallback classification
    3. Generate a clarifying response to the user
    4. Update training data for improvement

    Args:
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

    Returns:
        HandlerResult with processing outcome
    """
    logger.warning(
        "❔ [UNKNOWN] Could not classify message",
        extra={
            "platform": request.platform,
            "user_id": request.platform_user_id,
            "raw_content": request.raw_content[:200] if request.raw_content else None,
            "reason": extracted.extra.get("reason"),
            "possible_types": extracted.extra.get("possible_types"),
            "session_id": session_id,
        },
    )

    # TODO: Implement unknown message handling
    # 1. Log for analysis and model improvement
    # 2. Send clarifying response to user
    # 3. Store for manual review

    logger.debug("Unknown handler completed (stub implementation)")

    return HandlerResult(
        success=True,
        handler_name="handle_unknown",
        content_type=ContentType.UNKNOWN,
        data={
            "raw_content_preview": request.raw_content[:100] if request.raw_content else None,
            "reason": extracted.extra.get("reason"),
            "possible_types": extracted.extra.get("possible_types"),
            "status": "needs_clarification",
        },
        message="Could not understand your message. Please try rephrasing or provide more context.",
        follow_up_actions=["request_clarification", "log_for_review"],
    )


# Handler registry for dynamic dispatch
HANDLER_REGISTRY = {
    ContentType.PLACE_NAME: handle_place_name,
    ContentType.QUESTION: handle_question,
    ContentType.INSTAGRAM_LINK: handle_instagram_link,
    ContentType.TIKTOK_LINK: handle_tiktok_link,
    ContentType.OTHER_LINK: handle_other_link,
    ContentType.UNKNOWN: handle_unknown,
}


async def dispatch_handler(
    content_type: ContentType,
    request: UnifiedRequest,
    extracted: ExtractedData,
    session_id: Optional[str] = None,
) -> HandlerResult:
    """
    Dispatch to the appropriate handler based on content type.

    Args:
        content_type: The classified content type
        request: The unified incoming request
        extracted: Extracted data from classification
        session_id: Optional session ID for context

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

    return await handler(request, extracted, session_id)
