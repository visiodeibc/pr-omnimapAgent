"""
Agent Orchestrator for processing incoming messages.

This module contains the main orchestrator that:
1. Receives incoming messages from any platform
2. Uses OpenAI function calling to classify content type
3. Extracts structured data from the message
4. Routes to the appropriate handler

Uses OpenAI's function calling for intelligent classification and routing.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

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
)
from logging_config import get_logger

logger = get_logger(__name__)


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

    if function_name == "classify_as_question":
        return ContentType.QUESTION, ExtractedData(
            content_type=ContentType.QUESTION,
            confidence=confidence,
            question_text=arguments.get("question_text"),
            question_topic=arguments.get("topic"),
            question_intent=arguments.get("intent"),
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

    # Default to unknown
    return ContentType.UNKNOWN, ExtractedData(
        content_type=ContentType.UNKNOWN,
        confidence=confidence,
        extra={
            "reason": arguments.get("reason", "Unknown classification"),
            "possible_types": arguments.get("possible_types", []),
        },
    )


class AgentOrchestrator:
    """
    Orchestrator for the agentic message processing workflow.

    This class coordinates:
    1. Converting platform-specific messages to unified requests
    2. Classifying message content using OpenAI function calling
    3. Routing to appropriate handlers based on classification
    4. Managing database operations for request tracking
    """

    def __init__(
        self,
        openai_api_key: str,
        model: str = "gpt-4o-mini",
        supabase_client: Optional[Any] = None,
    ) -> None:
        """
        Initialize the agent orchestrator.

        Args:
            openai_api_key: OpenAI API key for function calling
            model: OpenAI model to use (default: gpt-4o-mini for cost efficiency)
            supabase_client: Optional Supabase client for database operations
        """
        self._openai = AsyncOpenAI(api_key=openai_api_key)
        self._model = model
        self._supabase = supabase_client

        logger.info(
            "AgentOrchestrator initialized",
            extra={"model": model, "has_supabase": supabase_client is not None},
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
    ) -> Tuple[ContentType, ExtractedData]:
        """
        Classify the content type of a message using OpenAI function calling.

        This is the core AI step that determines how to route the message.

        Args:
            request: Unified request to classify

        Returns:
            Tuple of (ContentType, ExtractedData)
        """
        if not request.raw_content:
            logger.warning(
                "Empty content in request, classifying as unknown",
                extra={"platform": request.platform, "user_id": request.platform_user_id},
            )
            return ContentType.UNKNOWN, ExtractedData(
                content_type=ContentType.UNKNOWN,
                confidence=1.0,
                extra={"reason": "Empty message content"},
            )

        logger.info(
            "Classifying content with OpenAI",
            extra={
                "platform": request.platform,
                "user_id": request.platform_user_id,
                "content_preview": request.raw_content[:100],
            },
        )

        try:
            response = await self._openai.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                    {"role": "user", "content": request.raw_content},
                ],
                tools=CONTENT_CLASSIFICATION_FUNCTIONS,
                tool_choice="required",  # Force the model to call a function
            )

            # Parse the function call
            message = response.choices[0].message
            if not message.tool_calls:
                logger.warning(
                    "No tool calls in response",
                    extra={"response": str(response)},
                )
                return ContentType.UNKNOWN, ExtractedData(
                    content_type=ContentType.UNKNOWN,
                    confidence=0.5,
                    extra={"reason": "Model did not call a classification function"},
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
            return ContentType.UNKNOWN, ExtractedData(
                content_type=ContentType.UNKNOWN,
                confidence=0.0,
                extra={"reason": f"Classification error: {str(exc)}"},
            )

    async def process_incoming_message(
        self,
        incoming: IncomingMessage,
        session_id: Optional[str] = None,
    ) -> HandlerResult:
        """
        Process an incoming message through the full agentic pipeline.

        This is the main entry point that orchestrates:
        1. Convert to unified request
        2. Classify content
        3. Route to handler
        4. Track in database

        Args:
            incoming: Platform-specific incoming message
            session_id: Optional session ID for context

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

        # Step 1: Convert to unified request
        request = self.convert_to_unified_request(incoming)

        # Step 2: Store incoming request in database (if available)
        request_id = None
        if self._supabase:
            request_id = await self._store_incoming_request(request, session_id)

        # Step 3: Classify content
        content_type, extracted = await self.classify_content(request)

        # Step 4: Update request with classification (if stored)
        if self._supabase and request_id:
            await self._update_request_classification(request_id, content_type, extracted)

        # Step 5: Dispatch to handler
        result = await dispatch_handler(content_type, request, extracted, session_id)

        # Step 6: Update request status (if stored)
        if self._supabase and request_id:
            await self._complete_request(request_id, result)

        logger.info(
            "Message processing completed",
            extra={
                "content_type": content_type.value,
                "handler": result.handler_name,
                "success": result.success,
                "request_id": request_id,
            },
        )

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
            return ContentType.UNKNOWN, ExtractedData(
                content_type=ContentType.UNKNOWN,
                confidence=1.0,
                extra={"reason": "Empty content"},
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
                return ContentType.UNKNOWN, ExtractedData(
                    content_type=ContentType.UNKNOWN,
                    confidence=0.5,
                    extra={"reason": "No tool call in response"},
                )

            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            return _parse_classification_result(function_name, arguments)

        except Exception as exc:
            logger.exception("Sync classification error", extra={"error": str(exc)})
            return ContentType.UNKNOWN, ExtractedData(
                content_type=ContentType.UNKNOWN,
                confidence=0.0,
                extra={"reason": f"Error: {str(exc)}"},
            )
