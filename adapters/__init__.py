"""
Messaging adapters for multi-platform support.

This module provides a unified interface for sending messages across
different chat platforms (Telegram, Instagram, TikTok, etc.).

Usage:
    from adapters import get_adapter_registry, Platform
    from adapters.telegram import TelegramAdapter

    # Register an adapter
    registry = get_adapter_registry()
    registry.register(TelegramAdapter(bot))

    # Send a message to any platform
    adapter = registry.get(Platform.TELEGRAM)
    result = await adapter.send_text(chat_id="12345", text="Hello!")
"""

from adapters.base import (
    AdapterCapabilities,
    ChatInfo,
    IncomingMessage,
    MessageDeliveryResult,
    MessagingAdapter,
    OutgoingMessage,
    Platform,
    UserInfo,
)
from adapters.registry import AdapterRegistry, get_adapter_registry, reset_registry

__all__ = [
    # Base classes
    "MessagingAdapter",
    "IncomingMessage",
    "OutgoingMessage",
    "MessageDeliveryResult",
    "AdapterCapabilities",
    "UserInfo",
    "ChatInfo",
    "Platform",
    # Registry
    "AdapterRegistry",
    "get_adapter_registry",
    "reset_registry",
]
