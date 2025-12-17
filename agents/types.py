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
    CONVERSATION = "conversation"  # Questions, greetings, general chat
    INSTAGRAM_LINK = "instagram_link"  # Link to Instagram post/reel
    TIKTOK_LINK = "tiktok_link"  # Link to TikTok post/reel
    OTHER_LINK = "other_link"  # Other URL links


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
    - CONVERSATION: message_text, topic, intent (questions, greetings, general chat)
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

    # Conversation-related fields (questions, greetings, general chat)
    message_text: Optional[str] = None
    message_topic: Optional[str] = None
    message_intent: Optional[str] = None

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
        if self.message_text:
            result["message_text"] = self.message_text
        if self.message_topic:
            result["message_topic"] = self.message_topic
        if self.message_intent:
            result["message_intent"] = self.message_intent
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
            "name": "classify_as_conversation",
            "description": "Classify the message as general conversation. Use this for: questions, greetings (hi, hello), casual chat, requests for help, unclear messages, or anything that doesn't fit other categories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_text": {
                        "type": "string",
                        "description": "The full message text",
                    },
                    "topic": {
                        "type": "string",
                        "description": "The topic (e.g., 'greeting', 'question', 'help_request', 'place_info', 'how_to_use', 'general', 'unclear')",
                    },
                    "intent": {
                        "type": "string",
                        "description": "The intent (e.g., 'greet', 'get_info', 'get_recommendation', 'get_help', 'chat', 'unclear')",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level from 0.0 to 1.0",
                    },
                },
                "required": ["message_text", "confidence"],
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
]


# Memory-related function definitions for the agent
# These allow the agent to explicitly query or save important information
MEMORY_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_memory",
            "description": "Search the user's conversation history for relevant context. Use this when the current message references past conversations, previously mentioned places, or needs historical context to understand properly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the conversation history (e.g., 'previously mentioned restaurants', 'places near Tokyo')",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["recent", "all"],
                        "description": "Time range to search: 'recent' for current session only, 'all' for all history",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why this memory lookup is needed",
                    },
                },
                "required": ["query", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_to_memory",
            "description": "Save important information for long-term recall. Use this for user preferences, frequently mentioned places, or context that should be remembered across sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The information to remember",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["preference", "place", "context"],
                        "description": "Category of information: 'preference' for user settings, 'place' for locations, 'context' for other important info",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this information should be saved for future reference",
                    },
                },
                "required": ["content", "category", "reason"],
            },
        },
    },
]


# System prompt for the classification agent
CLASSIFICATION_SYSTEM_PROMPT = """You are a message classification agent for OmniMap, a service that helps users discover and manage places.

Your job is to analyze incoming messages and classify them into one of these categories:
1. **place_name**: The message mentions a specific place (restaurant, cafe, hotel, landmark, etc.)
2. **conversation**: Questions, greetings (hi, hello), requests for help, general chat, or unclear messages
3. **instagram_link**: The message contains an Instagram URL (post, reel, story)
4. **tiktok_link**: The message contains a TikTok URL
5. **other_link**: The message contains some other URL

Guidelines:
- Look for Instagram URLs like: instagram.com/p/..., instagram.com/reel/..., instagr.am/...
- Look for TikTok URLs like: tiktok.com/@user/video/..., vm.tiktok.com/...
- A place name might be mentioned alongside a question - in that case, classify based on the primary intent
- Use 'conversation' for greetings, questions, help requests, and anything that doesn't fit other categories
- Extract as much structured data as possible from the message

Always call exactly one classification function based on your analysis."""


# System prompt template with conversation context
CLASSIFICATION_SYSTEM_PROMPT_WITH_CONTEXT_TEMPLATE = """You are a message classification agent for OmniMap, a service that helps users discover and manage places.

Your job is to analyze incoming messages and classify them into one of these categories:
1. **place_name**: The message mentions a specific place (restaurant, cafe, hotel, landmark, etc.)
2. **conversation**: Questions, greetings (hi, hello), requests for help, general chat, or unclear messages
3. **instagram_link**: The message contains an Instagram URL (post, reel, story)
4. **tiktok_link**: The message contains a TikTok URL
5. **other_link**: The message contains some other URL

## Recent Conversation Context
The following is the recent conversation history with this user. Use it to understand context, references to previous messages, and the user's ongoing intent:

{conversation_history}

## Guidelines
- Consider the conversation context when classifying messages
- The user may reference previous messages (e.g., "that place", "the one I mentioned")
- If the user asks a follow-up question about a previously mentioned place, classify based on their current intent
- Look for Instagram URLs like: instagram.com/p/..., instagram.com/reel/..., instagr.am/...
- Look for TikTok URLs like: tiktok.com/@user/video/..., vm.tiktok.com/...
- A place name might be mentioned alongside a question - classify based on the primary intent
- Use 'conversation' for greetings, questions, help requests, and anything that doesn't fit other categories
- Extract as much structured data as possible from the message

Always call exactly one classification function based on your analysis."""


def build_classification_prompt_with_context(conversation_history: str) -> str:
    """
    Build a classification system prompt that includes conversation context.

    Args:
        conversation_history: Formatted string of recent conversation messages

    Returns:
        Complete system prompt with conversation context
    """
    if not conversation_history:
        return CLASSIFICATION_SYSTEM_PROMPT

    return CLASSIFICATION_SYSTEM_PROMPT_WITH_CONTEXT_TEMPLATE.format(
        conversation_history=conversation_history
    )


# System prompt for generating contextual responses to conversation messages
CONVERSATION_RESPONSE_SYSTEM_PROMPT = """You are OmniMap, a helpful assistant that helps users discover and manage places from social media content.

Your capabilities:
- Extract place names and locations from Instagram/TikTok links
- Search for places and provide Google Maps links
- Answer questions about places and your service

When responding to messages:
1. Be friendly and conversational
2. If the user seems to be greeting you, respond warmly and explain what you can do
3. If the user asks a question, answer it helpfully
4. If the user's intent is unclear, politely ask for clarification
5. If the message seems like casual conversation, engage briefly but guide them toward your main features
6. Keep responses concise (1-3 sentences typically)
7. Use the conversation history to provide context-aware responses

IMPORTANT - Formatting rules:
- Use HTML formatting for text styling (the response will be sent to Telegram)
- Use <b>text</b> for bold (NOT **text**)
- Use <i>text</i> for italics (NOT *text*)
- Use <a href="url">text</a> for links
- Do NOT use Markdown formatting

Remember: You help users extract and discover places from social media content."""

CONVERSATION_RESPONSE_WITH_CONTEXT_TEMPLATE = """You are OmniMap, a helpful assistant that helps users discover and manage places from social media content.

Your capabilities:
- Extract place names and locations from Instagram/TikTok links
- Search for places and provide Google Maps links
- Answer questions about places and your service

## Recent Conversation Context
{conversation_history}

## Guidelines for Responding
When responding to the current message:
1. Be friendly and conversational
2. Use the conversation history to understand context and references
3. If the user seems to be greeting you, respond warmly and explain what you can do
4. If the user asks a question, answer it helpfully
5. If the user's intent is unclear, politely ask for clarification
6. If the message seems like casual conversation, engage briefly but guide them toward your main features
7. Keep responses concise (1-3 sentences typically)
8. If the user refers to something from the conversation history, acknowledge it

IMPORTANT - Formatting rules:
- Use HTML formatting for text styling (the response will be sent to Telegram)
- Use <b>text</b> for bold (NOT **text**)
- Use <i>text</i> for italics (NOT *text*)
- Use <a href="url">text</a> for links
- Do NOT use Markdown formatting

Remember: You help users extract and discover places from social media content."""


def build_conversation_response_prompt(conversation_history: str) -> str:
    """
    Build a system prompt for generating responses to conversation messages.

    Args:
        conversation_history: Formatted string of recent conversation messages

    Returns:
        Complete system prompt for conversation response generation
    """
    if not conversation_history:
        return CONVERSATION_RESPONSE_SYSTEM_PROMPT

    return CONVERSATION_RESPONSE_WITH_CONTEXT_TEMPLATE.format(
        conversation_history=conversation_history
    )
