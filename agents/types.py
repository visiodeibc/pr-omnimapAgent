"""
Type definitions for the agentic workflow.

This module defines the data structures used throughout the agent pipeline
for message classification, data extraction, and handler communication.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ContentType(str, Enum):
    """
    Classification of incoming message content.

    Used by the AI agent to determine how to process and route messages.
    """

    PLACE_NAME = "place_name"  # User mentioned a place name
    QUESTION = "question"  # User asked a question
    INSTAGRAM_LINK = "instagram_link"  # Link to Instagram post/reel
    TIKTOK_LINK = "tiktok_link"  # Link to TikTok post/reel
    OTHER_LINK = "other_link"  # Other URL links
    UNKNOWN = "unknown"  # Could not classify


@dataclass
class UnifiedRequest:
    """
    A unified, platform-agnostic representation of an incoming request.

    This is the first output of the agent pipeline - a standardized
    structure extracted from platform-specific webhook payloads.
    """

    # Platform identification
    platform: str  # telegram, instagram, tiktok
    platform_user_id: str
    platform_chat_id: Optional[str] = None
    message_id: Optional[str] = None

    # Sender information
    sender_username: Optional[str] = None
    sender_display_name: Optional[str] = None

    # Message content
    raw_content: Optional[str] = None
    media_urls: List[str] = field(default_factory=list)
    media_type: Optional[str] = None

    # Metadata
    timestamp: Optional[datetime] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "platform": self.platform,
            "platform_user_id": self.platform_user_id,
            "platform_chat_id": self.platform_chat_id,
            "message_id": self.message_id,
            "sender_username": self.sender_username,
            "sender_display_name": self.sender_display_name,
            "raw_content": self.raw_content,
            "media_urls": self.media_urls,
            "media_type": self.media_type,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata,
        }


@dataclass
class ExtractedData:
    """
    Structured data extracted from a classified message.

    The content varies based on the content_type:
    - PLACE_NAME: place_name, location_hints, confidence
    - QUESTION: question_text, topic, intent
    - INSTAGRAM_LINK: url, post_id, username, content_type (post/reel)
    - TIKTOK_LINK: url, video_id, username
    - OTHER_LINK: url, domain, description
    """

    content_type: ContentType

    # Common fields
    confidence: float = 0.0  # 0.0 to 1.0 confidence in classification

    # Place-related fields
    place_name: Optional[str] = None
    location_hints: List[str] = field(default_factory=list)

    # Question-related fields
    question_text: Optional[str] = None
    question_topic: Optional[str] = None
    question_intent: Optional[str] = None

    # Link-related fields
    url: Optional[str] = None
    link_domain: Optional[str] = None
    link_content_id: Optional[str] = None  # post_id, video_id, etc.
    link_username: Optional[str] = None  # username from the link
    link_type: Optional[str] = None  # post, reel, video, etc.

    # Additional extracted data
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "content_type": self.content_type.value,
            "confidence": self.confidence,
        }

        # Add non-None fields
        if self.place_name:
            result["place_name"] = self.place_name
        if self.location_hints:
            result["location_hints"] = self.location_hints
        if self.question_text:
            result["question_text"] = self.question_text
        if self.question_topic:
            result["question_topic"] = self.question_topic
        if self.question_intent:
            result["question_intent"] = self.question_intent
        if self.url:
            result["url"] = self.url
        if self.link_domain:
            result["link_domain"] = self.link_domain
        if self.link_content_id:
            result["link_content_id"] = self.link_content_id
        if self.link_username:
            result["link_username"] = self.link_username
        if self.link_type:
            result["link_type"] = self.link_type
        if self.extra:
            result["extra"] = self.extra

        return result


@dataclass
class HandlerResult:
    """
    Result returned by a content handler function.

    Each handler processes a specific content type and returns this
    standardized result for tracking and response generation.
    """

    success: bool
    handler_name: str
    content_type: ContentType

    # Result data
    data: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None  # Human-readable result message

    # Error information (if success=False)
    error: Optional[str] = None
    error_code: Optional[str] = None

    # Follow-up actions
    follow_up_actions: List[str] = field(default_factory=list)
    jobs_created: List[str] = field(default_factory=list)  # Job IDs

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "handler_name": self.handler_name,
            "content_type": self.content_type.value,
            "data": self.data,
            "message": self.message,
            "error": self.error,
            "error_code": self.error_code,
            "follow_up_actions": self.follow_up_actions,
            "jobs_created": self.jobs_created,
        }


# OpenAI Function Calling Schema Definitions
# These define the functions that the AI can call to classify and route messages

CONTENT_CLASSIFICATION_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "classify_as_place_name",
            "description": "Classify the message as containing a place name. Use this when the user mentions a specific location, restaurant, cafe, hotel, landmark, or any geographical place.",
            "parameters": {
                "type": "object",
                "properties": {
                    "place_name": {
                        "type": "string",
                        "description": "The extracted place name",
                    },
                    "location_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional context clues about the location (city, country, neighborhood, etc.)",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level from 0.0 to 1.0",
                    },
                },
                "required": ["place_name", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_as_question",
            "description": "Classify the message as a question. Use this when the user is asking for information, help, or clarification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_text": {
                        "type": "string",
                        "description": "The full question text",
                    },
                    "topic": {
                        "type": "string",
                        "description": "The topic of the question (e.g., 'place_info', 'directions', 'recommendations', 'how_to_use', 'general')",
                    },
                    "intent": {
                        "type": "string",
                        "description": "The intent behind the question (e.g., 'get_info', 'get_recommendation', 'get_help')",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level from 0.0 to 1.0",
                    },
                },
                "required": ["question_text", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_as_instagram_link",
            "description": "Classify the message as containing an Instagram link (post, reel, or story URL).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full Instagram URL",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "The post or reel ID extracted from the URL",
                    },
                    "username": {
                        "type": "string",
                        "description": "The Instagram username if present in the URL",
                    },
                    "content_type": {
                        "type": "string",
                        "enum": ["post", "reel", "story", "unknown"],
                        "description": "Type of Instagram content",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level from 0.0 to 1.0",
                    },
                },
                "required": ["url", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_as_tiktok_link",
            "description": "Classify the message as containing a TikTok link (video URL).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full TikTok URL",
                    },
                    "video_id": {
                        "type": "string",
                        "description": "The video ID extracted from the URL",
                    },
                    "username": {
                        "type": "string",
                        "description": "The TikTok username if present in the URL",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level from 0.0 to 1.0",
                    },
                },
                "required": ["url", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_as_other_link",
            "description": "Classify the message as containing a non-Instagram/TikTok link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL",
                    },
                    "domain": {
                        "type": "string",
                        "description": "The domain of the URL",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the link might contain",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level from 0.0 to 1.0",
                    },
                },
                "required": ["url", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_as_unknown",
            "description": "Use this when the message cannot be confidently classified into any other category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why classification failed",
                    },
                    "possible_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of content types this might be",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

# System prompt for the classification agent
CLASSIFICATION_SYSTEM_PROMPT = """You are a message classification agent for OmniMap, a service that helps users discover and manage places.

Your job is to analyze incoming messages and classify them into one of these categories:
1. **place_name**: The message mentions a specific place (restaurant, cafe, hotel, landmark, etc.)
2. **question**: The message is asking a question
3. **instagram_link**: The message contains an Instagram URL (post, reel, story)
4. **tiktok_link**: The message contains a TikTok URL
5. **other_link**: The message contains some other URL
6. **unknown**: Cannot confidently classify

Guidelines:
- Look for Instagram URLs like: instagram.com/p/..., instagram.com/reel/..., instagr.am/...
- Look for TikTok URLs like: tiktok.com/@user/video/..., vm.tiktok.com/...
- A place name might be mentioned alongside a question - in that case, classify based on the primary intent
- Be confident in your classification - only use 'unknown' when truly uncertain
- Extract as much structured data as possible from the message

Always call exactly one classification function based on your analysis."""
