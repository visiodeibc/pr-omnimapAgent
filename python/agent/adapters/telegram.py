"""
Telegram messaging adapter.

Implements the MessagingAdapter interface for Telegram using python-telegram-bot.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

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

logger = logging.getLogger(__name__)


class TelegramAdapter(MessagingAdapter):
    """
    Telegram messaging adapter using python-telegram-bot.

    Handles sending messages to Telegram users and parsing incoming webhooks.
    """

    def __init__(self, bot: Bot) -> None:
        """
        Initialize the Telegram adapter.

        Args:
            bot: An initialized python-telegram-bot Bot instance.
        """
        self._bot = bot

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_buttons=True,
            supports_markdown=True,
            supports_html=True,
            supports_media=True,
            supports_replies=True,
            supports_editing=True,
            supports_deletion=True,
            max_message_length=4096,
            supported_media_types=["image", "video", "audio", "document", "sticker"],
        )

    async def send_message(self, message: OutgoingMessage) -> MessageDeliveryResult:
        """Send a message to a Telegram chat."""
        try:
            kwargs: Dict[str, Any] = {}

            # Parse mode
            if message.parse_mode:
                kwargs["parse_mode"] = message.parse_mode

            # Reply context
            if message.reply_to_message_id:
                kwargs["reply_to_message_id"] = int(message.reply_to_message_id)

            # Notification setting
            if message.disable_notification:
                kwargs["disable_notification"] = True

            # Inline keyboard buttons
            if message.buttons:
                keyboard = []
                for btn in message.buttons:
                    if "url" in btn:
                        keyboard.append(
                            [InlineKeyboardButton(btn["text"], url=btn["url"])]
                        )
                    elif "callback_data" in btn:
                        keyboard.append(
                            [
                                InlineKeyboardButton(
                                    btn["text"], callback_data=btn["callback_data"]
                                )
                            ]
                        )
                if keyboard:
                    kwargs["reply_markup"] = InlineKeyboardMarkup(keyboard)

            # Send the message
            chat_id = int(message.chat_id)
            sent = await self._bot.send_message(chat_id, message.text, **kwargs)

            return MessageDeliveryResult(
                success=True,
                message_id=str(sent.message_id),
                metadata={"chat_id": chat_id},
            )

        except Exception as exc:
            logger.exception("Failed to send Telegram message: %s", exc)
            return MessageDeliveryResult(
                success=False,
                error=str(exc),
                error_code=getattr(exc, "error_code", None),
            )

    def send_message_sync(self, message: OutgoingMessage) -> MessageDeliveryResult:
        """
        Synchronous wrapper for send_message.

        Useful when calling from a sync context (e.g., worker thread).
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.send_message(message))
        finally:
            loop.close()

    def parse_incoming(self, raw_payload: Dict[str, Any]) -> Optional[IncomingMessage]:
        """Parse a Telegram webhook update into an IncomingMessage."""
        try:
            # Handle regular messages
            msg = raw_payload.get("message") or raw_payload.get("edited_message")
            if not msg:
                # Could be a callback query, channel post, etc.
                return None

            # Extract user info
            from_user = msg.get("from", {})
            user = UserInfo(
                platform_user_id=str(from_user.get("id", "")),
                username=from_user.get("username"),
                first_name=from_user.get("first_name"),
                last_name=from_user.get("last_name"),
                language_code=from_user.get("language_code"),
            )

            # Extract chat info
            chat_data = msg.get("chat", {})
            chat = ChatInfo(
                platform_chat_id=str(chat_data.get("id", "")),
                title=chat_data.get("title"),
                chat_type=chat_data.get("type", "private"),
            )

            # Extract text
            text = msg.get("text") or msg.get("caption")

            # Extract media
            media_urls = []
            media_type = None
            if msg.get("photo"):
                media_type = "image"
                # Get largest photo
                photos = msg["photo"]
                if photos:
                    media_urls.append(photos[-1].get("file_id", ""))
            elif msg.get("video"):
                media_type = "video"
                media_urls.append(msg["video"].get("file_id", ""))
            elif msg.get("audio"):
                media_type = "audio"
                media_urls.append(msg["audio"].get("file_id", ""))
            elif msg.get("document"):
                media_type = "document"
                media_urls.append(msg["document"].get("file_id", ""))

            # Extract timestamp
            timestamp = None
            if msg.get("date"):
                timestamp = datetime.fromtimestamp(msg["date"], tz=timezone.utc)

            # Reply context
            reply_to = None
            if msg.get("reply_to_message"):
                reply_to = str(msg["reply_to_message"].get("message_id", ""))

            return IncomingMessage(
                platform=Platform.TELEGRAM,
                message_id=str(msg.get("message_id", "")),
                user=user,
                chat=chat,
                text=text,
                timestamp=timestamp,
                media_urls=media_urls,
                media_type=media_type,
                raw_payload=raw_payload,
                reply_to_message_id=reply_to,
            )

        except Exception as exc:
            logger.exception("Failed to parse Telegram message: %s", exc)
            return None

    def validate_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Validate Telegram webhook using secret token header.

        Note: Actual validation requires comparing the X-Telegram-Bot-Api-Secret-Token
        header with the configured secret. This should be done at the route level
        since we need access to settings.
        """
        # The actual token validation happens in the webhook route
        # This method can be extended for additional validation
        return True
