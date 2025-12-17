"""
Agent Orchestrator for processing incoming messages.

This module contains the main orchestrator that:
1. Receives incoming messages from any platform
2. Manages session memory and conversation context
3. Uses OpenAI function calling to classify content type
4. Extracts structured data from the message
5. Routes to the appropriate handler

Uses OpenAI's function calling for intelligent classification and routing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI, OpenAI

from adapters.base import IncomingMessage, Platform
from agents.handlers import dispatch_handler
from agents.types import (
    CLASSIFICATION_SYSTEM_PROMPT,
    CONTENT_CLASSIFICATION_FUNCTIONS,
    ContentType,
    ExtractedData,
    HandlerResult,
    UnifiedRequest,
    build_classification_prompt_with_context,
)
from logging_config import get_logger
from services.memory import ConversationContext, MemoryService

if TYPE_CHECKING:
    from debug_reporter import DebugReporter

logger = get_logger(__name__)

# Default inactivity threshold for session expiration (minutes)
SESSION_INACTIVITY_THRESHOLD_MINUTES = 30


def _parse_classification_result(
    function_name: str,
    arguments: Dict[str, Any],
) -> Tuple[ContentType, ExtractedData]:
    """
    Parse the OpenAI function call result into ContentType and ExtractedData.

    Args:
        function_name: Name of the function called
        arguments: Arguments passed to the function

    Returns:
        Tuple of (ContentType, ExtractedData)
    """
    confidence = arguments.get("confidence", 0.8)

    if function_name == "classify_as_place_name":
        return ContentType.PLACE_NAME, ExtractedData(
            content_type=ContentType.PLACE_NAME,
            confidence=confidence,
            place_name=arguments.get("place_name"),
            location_hints=arguments.get("location_hints", []),
        )

    if function_name == "classify_as_conversation":
        return ContentType.CONVERSATION, ExtractedData(
            content_type=ContentType.CONVERSATION,
            confidence=confidence,
            message_text=arguments.get("message_text"),
            message_topic=arguments.get("topic"),
            message_intent=arguments.get("intent"),
        )

    if function_name == "classify_as_instagram_link":
        return ContentType.INSTAGRAM_LINK, ExtractedData(
            content_type=ContentType.INSTAGRAM_LINK,
            confidence=confidence,
            url=arguments.get("url"),
            link_content_id=arguments.get("content_id"),
            link_username=arguments.get("username"),
            link_type=arguments.get("content_type"),
            link_domain="instagram.com",
        )

    if function_name == "classify_as_tiktok_link":
        return ContentType.TIKTOK_LINK, ExtractedData(
            content_type=ContentType.TIKTOK_LINK,
            confidence=confidence,
            url=arguments.get("url"),
            link_content_id=arguments.get("video_id"),
            link_username=arguments.get("username"),
            link_domain="tiktok.com",
        )

    if function_name == "classify_as_other_link":
        return ContentType.OTHER_LINK, ExtractedData(
            content_type=ContentType.OTHER_LINK,
            confidence=confidence,
            url=arguments.get("url"),
            link_domain=arguments.get("domain"),
            extra={"description": arguments.get("description")},
        )

    # Default to conversation for any unrecognized classification
    return ContentType.CONVERSATION, ExtractedData(
        content_type=ContentType.CONVERSATION,
        confidence=confidence,
        message_text=arguments.get("message_text", ""),
        message_topic="unclear",
        message_intent="unclear",
    )


class AgentOrchestrator:
    """
    Orchestrator for the agentic message processing workflow.

    This class coordinates:
    1. Converting platform-specific messages to unified requests
    2. Managing session memory and conversation context
    3. Classifying message content using OpenAI function calling
    4. Routing to appropriate handlers based on classification
    5. Managing database operations for request tracking
    """

    def __init__(
        self,
        openai_api_key: str,
        model: str = "gpt-4o-mini",
        supabase_client: Optional[Any] = None,
        inactivity_threshold_minutes: int = SESSION_INACTIVITY_THRESHOLD_MINUTES,
    ) -> None:
        """
        Initialize the agent orchestrator.

        Args:
            openai_api_key: OpenAI API key for function calling
            model: OpenAI model to use (default: gpt-4o-mini for cost efficiency)
            supabase_client: Optional Supabase client for database operations
            inactivity_threshold_minutes: Minutes of inactivity before session expires (default 30)
        """
        self._openai = AsyncOpenAI(api_key=openai_api_key)
        self._model = model
        self._supabase = supabase_client
        self._inactivity_threshold = inactivity_threshold_minutes

        # Initialize memory service if Supabase is available
        self._memory_service: Optional[MemoryService] = None
        if supabase_client:
            self._memory_service = MemoryService(supabase_client)

        logger.info(
            "AgentOrchestrator initialized",
            extra={
                "model": model,
                "has_supabase": supabase_client is not None,
                "inactivity_threshold_minutes": inactivity_threshold_minutes,
            },
        )

    def convert_to_unified_request(
        self,
        incoming: IncomingMessage,
    ) -> UnifiedRequest:
        """
        Convert an IncomingMessage to a UnifiedRequest.

        This normalizes the platform-specific message into a standard format
        that the classification agent can process.

        Args:
            incoming: Platform-specific incoming message

        Returns:
            Unified request structure
        """
        logger.debug(
            "Converting incoming message to unified request",
            extra={
                "platform": incoming.platform.value,
                "message_id": incoming.message_id,
            },
        )

        return UnifiedRequest(
            platform=incoming.platform.value,
            platform_user_id=incoming.user.platform_user_id,
            platform_chat_id=incoming.chat.platform_chat_id,
            message_id=incoming.message_id,
            sender_username=incoming.user.username,
            sender_display_name=incoming.user.display_name,
            raw_content=incoming.text,
            media_urls=incoming.media_urls,
            media_type=incoming.media_type,
            timestamp=incoming.timestamp,
            raw_payload=incoming.raw_payload,
            metadata=incoming.metadata,
        )

    async def classify_content(
        self,
        request: UnifiedRequest,
        conversation_context: Optional[ConversationContext] = None,
    ) -> Tuple[ContentType, ExtractedData]:
        """
        Classify the content type of a message using OpenAI function calling.

        This is the core AI step that determines how to route the message.
        When conversation context is provided, it's included in the prompt
        to help with context-dependent classification.

        Args:
            request: Unified request to classify
            conversation_context: Optional conversation context for better classification

        Returns:
            Tuple of (ContentType, ExtractedData)
        """
        if not request.raw_content:
            logger.warning(
                "Empty content in request, classifying as conversation",
                extra={"platform": request.platform, "user_id": request.platform_user_id},
            )
            return ContentType.CONVERSATION, ExtractedData(
                content_type=ContentType.CONVERSATION,
                confidence=1.0,
                message_text="",
                message_topic="empty",
                message_intent="unclear",
            )

        # Build system prompt with or without context
        if conversation_context and conversation_context.has_context():
            system_prompt = build_classification_prompt_with_context(
                self._memory_service.build_prompt_context(conversation_context)
                if self._memory_service
                else ""
            )
            has_context = True
        else:
            system_prompt = CLASSIFICATION_SYSTEM_PROMPT
            has_context = False

        logger.info(
            "Classifying content with OpenAI",
            extra={
                "platform": request.platform,
                "user_id": request.platform_user_id,
                "content_preview": request.raw_content[:100],
                "has_conversation_context": has_context,
            },
        )

        try:
            response = await self._openai.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request.raw_content},
                ],
                tools=CONTENT_CLASSIFICATION_FUNCTIONS,
                tool_choice="required",  # Force the model to call a function
            )

            # Parse the function call
            message = response.choices[0].message
            if not message.tool_calls:
                logger.warning(
                    "No tool calls in response, defaulting to conversation",
                    extra={"response": str(response)},
                )
                return ContentType.CONVERSATION, ExtractedData(
                    content_type=ContentType.CONVERSATION,
                    confidence=0.5,
                    message_text=request.raw_content or "",
                    message_topic="unclear",
                    message_intent="unclear",
                )

            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            logger.debug(
                "OpenAI function call result",
                extra={
                    "function": function_name,
                    "arguments": arguments,
                },
            )

            # Map function name to content type and extracted data
            content_type, extracted = _parse_classification_result(
                function_name, arguments
            )

            logger.info(
                "Content classified successfully",
                extra={
                    "content_type": content_type.value,
                    "confidence": extracted.confidence,
                },
            )

            return content_type, extracted

        except Exception as exc:
            logger.exception(
                "Error classifying content with OpenAI",
                extra={"error": str(exc)},
            )
            return ContentType.CONVERSATION, ExtractedData(
                content_type=ContentType.CONVERSATION,
                confidence=0.0,
                message_text=request.raw_content or "",
                message_topic="error",
                message_intent="unclear",
                extra={"classification_error": str(exc)},
            )

    async def process_incoming_message(
        self,
        incoming: IncomingMessage,
        session_id: Optional[str] = None,
        debug_reporter: Optional["DebugReporter"] = None,
    ) -> HandlerResult:
        """
        Process an incoming message through the full agentic pipeline.

        This is the main entry point that orchestrates:
        1. Get or create active session (with 30-min timeout check)
        2. Load conversation context from memory
        3. Convert to unified request
        4. Classify content (with context)
        5. Route to handler
        6. Save messages to memory
        7. Track in database

        Args:
            incoming: Platform-specific incoming message
            session_id: Optional session ID for context (if not provided, will be determined from user)
            debug_reporter: Optional DebugReporter for dev logging to user

        Returns:
            HandlerResult from the appropriate handler
        """
        logger.info(
            "Processing incoming message through agent pipeline",
            extra={
                "platform": incoming.platform.value,
                "user_id": incoming.user.platform_user_id,
                "message_id": incoming.message_id,
                "session_id": session_id,
            },
        )

        # Debug: Log pipeline start
        if debug_reporter:
            debug_reporter.step("Pipeline started", data={
                "platform": incoming.platform.value,
                "user": incoming.user.display_name,
                "message_id": incoming.message_id,
            })

        # Step 1: Get or create active session
        conversation_context: Optional[ConversationContext] = None
        is_new_session = True

        if self._supabase and not session_id:
            try:
                # Parse chat_id as int if possible
                chat_id = None
                if incoming.chat.platform_chat_id:
                    try:
                        chat_id = int(incoming.chat.platform_chat_id)
                    except (ValueError, TypeError):
                        pass

                session, is_new_session = self._supabase.get_or_create_active_session(
                    platform=incoming.platform.value,
                    platform_user_id=incoming.user.platform_user_id,
                    platform_chat_id=chat_id,
                    inactivity_threshold_minutes=self._inactivity_threshold,
                    metadata={
                        "username": incoming.user.username,
                        "display_name": incoming.user.display_name,
                    },
                )
                session_id = session.get("id")

                if debug_reporter:
                    debug_reporter.step("Session resolved", data={
                        "session_id": session_id,
                        "is_new_session": is_new_session,
                    })

                logger.debug(
                    "Session resolved",
                    extra={
                        "session_id": session_id,
                        "is_new_session": is_new_session,
                    },
                )

            except Exception as exc:
                logger.warning(
                    "Failed to get/create session",
                    extra={"error": str(exc)},
                )

        # Step 2: Load conversation context from memory
        if self._memory_service and session_id:
            conversation_context = self._memory_service.load_context(
                session_id=session_id,
                is_new_session=is_new_session,
            )

            if debug_reporter:
                debug_reporter.step("Loaded conversation context", data={
                    "message_count": conversation_context.message_count,
                    "has_context": conversation_context.has_context(),
                })

        # Step 3: Convert to unified request
        request = self.convert_to_unified_request(incoming)
        if debug_reporter:
            debug_reporter.step("Converted to unified request", data={
                "content_preview": (request.raw_content or "")[:50],
            })

        # Step 4: Save user message to memory (before processing)
        if self._memory_service and session_id:
            self._memory_service.save_user_message(
                session_id=session_id,
                text=request.raw_content or "",
                platform=request.platform,
                platform_user_id=request.platform_user_id,
            )

        # Step 5: Store incoming request in database (if available)
        request_id = None
        if self._supabase:
            request_id = await self._store_incoming_request(request, session_id)
            if debug_reporter:
                debug_reporter.debug("Stored request in database", data={
                    "request_id": request_id,
                })

        # Step 6: Classify content (with conversation context)
        if debug_reporter:
            debug_reporter.step("Classifying content with OpenAI", data={
                "model": self._model,
                "has_context": conversation_context.has_context() if conversation_context else False,
            })

        content_type, extracted = await self.classify_content(
            request,
            conversation_context=conversation_context,
        )

        if debug_reporter:
            debug_reporter.success("Content classified", data={
                "content_type": content_type.value,
                "confidence": extracted.confidence,
            })

        # Step 7: Update request with classification (if stored)
        if self._supabase and request_id:
            await self._update_request_classification(request_id, content_type, extracted)

        # Step 8: Dispatch to handler (with context for handlers that need it)
        if debug_reporter:
            debug_reporter.step(f"Dispatching to handler: {content_type.value}")

        result = await dispatch_handler(
            content_type,
            request,
            extracted,
            session_id,
            conversation_context=conversation_context,
            memory_service=self._memory_service,
        )

        if debug_reporter:
            if result.success:
                debug_reporter.success("Handler completed", data={
                    "handler": result.handler_name,
                    "follow_up_actions": result.follow_up_actions,
                })
            else:
                debug_reporter.error("Handler failed", data={
                    "handler": result.handler_name,
                    "error": result.error,
                })

        # Step 9: Save assistant response to memory
        if self._memory_service and session_id and result.message:
            self._memory_service.save_assistant_message(
                session_id=session_id,
                text=result.message,
                handler_name=result.handler_name,
                content_type=content_type.value,
            )

        # Step 10: Update request status (if stored)
        if self._supabase and request_id:
            await self._complete_request(request_id, result)

        logger.info(
            "Message processing completed",
            extra={
                "content_type": content_type.value,
                "handler": result.handler_name,
                "success": result.success,
                "request_id": request_id,
                "session_id": session_id,
            },
        )

        # Debug: Log pipeline completion
        if debug_reporter:
            debug_reporter.step("Pipeline completed")

        return result

    async def process_raw_webhook(
        self,
        platform: Platform,
        raw_payload: Dict[str, Any],
        adapter: Any,
        session_id: Optional[str] = None,
    ) -> Optional[HandlerResult]:
        """
        Process a raw webhook payload from any platform.

        This method can be called directly from webhook endpoints to process
        any incoming webhook payload using the platform adapter for parsing.

        Args:
            platform: The source platform
            raw_payload: Raw webhook payload
            adapter: Platform adapter for parsing
            session_id: Optional session ID for context

        Returns:
            HandlerResult if processed, None if payload was not a message
        """
        logger.debug(
            "Processing raw webhook payload",
            extra={"platform": platform.value},
        )

        # Use adapter to parse into IncomingMessage
        incoming = adapter.parse_incoming(raw_payload)
        if not incoming:
            logger.debug(
                "Webhook payload was not a message, skipping",
                extra={"platform": platform.value},
            )
            return None

        return await self.process_incoming_message(incoming, session_id)

    # Database operations (stub implementations for async Supabase)

    async def _store_incoming_request(
        self,
        request: UnifiedRequest,
        session_id: Optional[str],
    ) -> Optional[str]:
        """Store an incoming request in the database."""
        if not self._supabase:
            return None

        try:
            # Note: This is a sync call - in production you'd want async Supabase
            # For now we use the sync client in an async context
            payload = {
                "platform": request.platform,
                "platform_user_id": request.platform_user_id,
                "platform_chat_id": request.platform_chat_id,
                "message_id": request.message_id,
                "raw_content": request.raw_content,
                "status": "processing",
                "session_id": session_id,
                "metadata": request.metadata,
                "raw_payload": request.raw_payload,
            }
            result = self._supabase.insert_incoming_request(payload)
            return result.get("id") if result else None
        except Exception as exc:
            logger.warning(
                "Failed to store incoming request",
                extra={"error": str(exc)},
            )
            return None

    async def _update_request_classification(
        self,
        request_id: str,
        content_type: ContentType,
        extracted: ExtractedData,
    ) -> None:
        """Update request with classification results."""
        if not self._supabase:
            return

        try:
            self._supabase.update_incoming_request(
                request_id,
                {
                    "content_type": content_type.value,
                    "extracted_data": extracted.to_dict(),
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to update request classification",
                extra={"request_id": request_id, "error": str(exc)},
            )

    async def _complete_request(
        self,
        request_id: str,
        result: HandlerResult,
    ) -> None:
        """Mark request as completed with result."""
        if not self._supabase:
            return

        try:
            status = "completed" if result.success else "failed"
            self._supabase.update_incoming_request(
                request_id,
                {
                    "status": status,
                    "error": result.error,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to complete request",
                extra={"request_id": request_id, "error": str(exc)},
            )


# Synchronous wrapper for use in sync contexts (e.g., worker)
class SyncAgentOrchestrator:
    """
    Synchronous wrapper for AgentOrchestrator.

    Use this in synchronous contexts like the worker thread.
    """

    def __init__(
        self,
        openai_api_key: str,
        model: str = "gpt-4o-mini",
        supabase_client: Optional[Any] = None,
    ) -> None:
        """Initialize the sync orchestrator."""
        self._openai = OpenAI(api_key=openai_api_key)
        self._model = model
        self._supabase = supabase_client

    def classify_content_sync(
        self,
        raw_content: str,
    ) -> Tuple[ContentType, ExtractedData]:
        """
        Synchronously classify content using OpenAI.

        Args:
            raw_content: Raw message content to classify

        Returns:
            Tuple of (ContentType, ExtractedData)
        """
        if not raw_content:
            return ContentType.CONVERSATION, ExtractedData(
                content_type=ContentType.CONVERSATION,
                confidence=1.0,
                message_text="",
                message_topic="empty",
                message_intent="unclear",
            )

        try:
            response = self._openai.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                    {"role": "user", "content": raw_content},
                ],
                tools=CONTENT_CLASSIFICATION_FUNCTIONS,
                tool_choice="required",
            )

            message = response.choices[0].message
            if not message.tool_calls:
                return ContentType.CONVERSATION, ExtractedData(
                    content_type=ContentType.CONVERSATION,
                    confidence=0.5,
                    message_text=raw_content,
                    message_topic="unclear",
                    message_intent="unclear",
                )

            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            return _parse_classification_result(function_name, arguments)

        except Exception as exc:
            logger.exception("Sync classification error", extra={"error": str(exc)})
            return ContentType.CONVERSATION, ExtractedData(
                content_type=ContentType.CONVERSATION,
                confidence=0.0,
                message_text=raw_content,
                message_topic="error",
                message_intent="unclear",
                extra={"classification_error": str(exc)},
            )
