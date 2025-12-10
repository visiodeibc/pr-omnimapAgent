"""
Base classes and types for messaging adapters.

This module defines the abstract interface that all platform adapters must implement,
enabling platform-agnostic message handling throughout the application.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Platform(str, Enum):
    """Supported messaging platforms."""

    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    WHATSAPP = "whatsapp"
    WEB = "web"


@dataclass
class UserInfo:
    """Platform-agnostic user information."""

    platform_user_id: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language_code: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Get a human-readable display name."""
        if self.first_name:
            parts = [self.first_name]
            if self.last_name:
                parts.append(self.last_name)
            return " ".join(parts)
        return self.username or self.platform_user_id


@dataclass
class ChatInfo:
    """Platform-agnostic chat/conversation information."""

    platform_chat_id: str
    title: Optional[str] = None
    chat_type: str = "private"  # private, group, channel, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IncomingMessage:
    """
    A normalized incoming message from any platform.

    This is the canonical representation of a message received from
    Telegram, Instagram, TikTok, or any other supported platform.
    """

    platform: Platform
    message_id: str
    user: UserInfo
    chat: ChatInfo
    text: Optional[str] = None
    timestamp: Optional[datetime] = None

    # Media attachments (URLs or identifiers)
    media_urls: List[str] = field(default_factory=list)
    media_type: Optional[str] = None  # image, video, audio, etc.

    # Original platform-specific payload for advanced use cases
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    # Reply context
    reply_to_message_id: Optional[str] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """
    A message to be sent to a user on any platform.

    The adapter will translate this into platform-specific API calls.
    """

    chat_id: str
    text: str
    platform: Optional[Platform] = None  # Determined by adapter if not set

    # Rich content (supported by some platforms)
    parse_mode: Optional[str] = None  # markdown, html, etc.
    buttons: Optional[List[Dict[str, str]]] = None  # Inline buttons/quick replies

    # Media (URL or file path)
    media_url: Optional[str] = None
    media_type: Optional[str] = None

    # Reply context
    reply_to_message_id: Optional[str] = None

    # Additional options
    disable_notification: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MessageDeliveryResult:
    """Result of attempting to deliver a message."""

    success: bool
    message_id: Optional[str] = None  # Platform's message ID if successful
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterCapabilities:
    """
    Describes what features a platform adapter supports.

    Allows the application to adapt its behavior based on platform capabilities.
    """

    supports_buttons: bool = False
    supports_markdown: bool = False
    supports_html: bool = False
    supports_media: bool = False
    supports_replies: bool = False
    supports_editing: bool = False
    supports_deletion: bool = False
    max_message_length: int = 4096
    supported_media_types: List[str] = field(default_factory=list)


class MessagingAdapter(ABC):
    """
    Abstract base class for platform messaging adapters.

    Each platform (Telegram, Instagram, TikTok) implements this interface
    to provide unified message sending/receiving capabilities.
    """

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Return the platform this adapter handles."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        """Return the capabilities of this adapter."""
        ...

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> MessageDeliveryResult:
        """
        Send a message to a user/chat.

        Args:
            message: The message to send.

        Returns:
            Result indicating success/failure and any metadata.
        """
        ...

    @abstractmethod
    def parse_incoming(self, raw_payload: Dict[str, Any]) -> Optional[IncomingMessage]:
        """
        Parse a raw webhook payload into a normalized IncomingMessage.

        Args:
            raw_payload: The raw JSON payload from the platform webhook.

        Returns:
            Normalized message, or None if the payload is not a message.
        """
        ...

    async def send_text(
        self,
        chat_id: str,
        text: str,
        **kwargs: Any,
    ) -> MessageDeliveryResult:
        """Convenience method to send a simple text message."""
        message = OutgoingMessage(
            chat_id=chat_id,
            text=text,
            platform=self.platform,
            **kwargs,
        )
        return await self.send_message(message)

    def validate_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Validate an incoming webhook request.

        Override this method to implement platform-specific signature validation.

        Args:
            headers: Request headers.
            body: Raw request body.

        Returns:
            True if the request is valid, False otherwise.
        """
        return True  # Default: no validation

    async def initialize(self) -> None:
        """
        Initialize the adapter (e.g., authenticate with the platform).

        Override if the adapter needs async initialization.
        """
        pass

    async def shutdown(self) -> None:
        """
        Clean up resources when shutting down.

        Override if the adapter needs async cleanup.
        """
        pass
