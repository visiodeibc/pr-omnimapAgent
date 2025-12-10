"""
Instagram Messenger adapter.

Implements the MessagingAdapter interface for Instagram using the Meta Graph API.
This adapter handles messages sent via Instagram Direct Messages.

Setup requirements:
1. Create a Meta App at https://developers.facebook.com/
2. Add Instagram Basic Display and Instagram Messaging products
3. Configure webhook for messages
4. Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_APP_SECRET in environment
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

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

# Instagram Graph API base URL
GRAPH_API_URL = "https://graph.facebook.com/v18.0"


class InstagramAdapter(MessagingAdapter):
    """
    Instagram Messaging adapter using Meta Graph API.

    Handles sending messages to Instagram users via the Instagram Messaging API.

    Reference: https://developers.facebook.com/docs/messenger-platform/instagram
    """

    def __init__(
        self,
        access_token: str,
        app_secret: Optional[str] = None,
        instagram_account_id: Optional[str] = None,
    ) -> None:
        """
        Initialize the Instagram adapter.

        Args:
            access_token: Page access token with instagram_basic and instagram_manage_messages permissions.
            app_secret: App secret for webhook signature validation.
            instagram_account_id: Instagram account ID for sending messages.
        """
        self._access_token = access_token
        self._app_secret = app_secret
        self._instagram_account_id = instagram_account_id
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def platform(self) -> Platform:
        return Platform.INSTAGRAM

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_buttons=True,  # Quick replies
            supports_markdown=False,
            supports_html=False,
            supports_media=True,
            supports_replies=True,
            supports_editing=False,
            supports_deletion=False,
            max_message_length=1000,
            supported_media_types=["image", "video", "audio"],
        )

    async def send_message(self, message: OutgoingMessage) -> MessageDeliveryResult:
        """Send a message to an Instagram user."""
        try:
            # Build the message payload
            payload: Dict[str, Any] = {
                "recipient": {"id": message.chat_id},
                "message": {"text": message.text},
            }

            # Add quick reply buttons if provided
            if message.buttons:
                quick_replies = []
                for btn in message.buttons[:13]:  # Instagram limits to 13 quick replies
                    quick_replies.append({
                        "content_type": "text",
                        "title": btn.get("text", "")[:20],  # Max 20 chars
                        "payload": btn.get("callback_data", btn.get("text", "")),
                    })
                if quick_replies:
                    payload["message"]["quick_replies"] = quick_replies

            # Send via Graph API
            url = f"{GRAPH_API_URL}/{self._instagram_account_id}/messages"
            params = {"access_token": self._access_token}

            response = await self._client.post(url, params=params, json=payload)
            response.raise_for_status()
            data = response.json()

            return MessageDeliveryResult(
                success=True,
                message_id=data.get("message_id"),
                metadata={"recipient_id": data.get("recipient_id")},
            )

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            logger.exception("Instagram API error: %s - %s", exc.response.status_code, error_body)
            return MessageDeliveryResult(
                success=False,
                error=f"HTTP {exc.response.status_code}: {error_body}",
                error_code=str(exc.response.status_code),
            )
        except Exception as exc:
            logger.exception("Failed to send Instagram message: %s", exc)
            return MessageDeliveryResult(
                success=False,
                error=str(exc),
            )

    def parse_incoming(self, raw_payload: Dict[str, Any]) -> Optional[IncomingMessage]:
        """Parse an Instagram webhook payload into an IncomingMessage."""
        try:
            # Instagram webhooks follow the Messenger platform format
            entry = raw_payload.get("entry", [])
            if not entry:
                return None

            for e in entry:
                messaging = e.get("messaging", [])
                for msg_event in messaging:
                    # Skip non-message events (read receipts, typing indicators, etc.)
                    message = msg_event.get("message")
                    if not message:
                        continue

                    sender = msg_event.get("sender", {})
                    recipient = msg_event.get("recipient", {})

                    # Extract user info
                    user = UserInfo(
                        platform_user_id=str(sender.get("id", "")),
                        metadata={"instagram_scoped_id": sender.get("id")},
                    )

                    # Extract chat info (for Instagram DM, chat_id is the sender ID)
                    chat = ChatInfo(
                        platform_chat_id=str(sender.get("id", "")),
                        chat_type="private",
                        metadata={"recipient_id": recipient.get("id")},
                    )

                    # Extract text
                    text = message.get("text")

                    # Extract media attachments
                    media_urls = []
                    media_type = None
                    attachments = message.get("attachments", [])
                    for att in attachments:
                        att_type = att.get("type")
                        payload = att.get("payload", {})
                        if att_type == "image":
                            media_type = "image"
                            media_urls.append(payload.get("url", ""))
                        elif att_type == "video":
                            media_type = "video"
                            media_urls.append(payload.get("url", ""))
                        elif att_type == "audio":
                            media_type = "audio"
                            media_urls.append(payload.get("url", ""))

                    # Extract timestamp
                    timestamp = None
                    ts = msg_event.get("timestamp")
                    if ts:
                        timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

                    return IncomingMessage(
                        platform=Platform.INSTAGRAM,
                        message_id=message.get("mid", ""),
                        user=user,
                        chat=chat,
                        text=text,
                        timestamp=timestamp,
                        media_urls=media_urls,
                        media_type=media_type,
                        raw_payload=raw_payload,
                    )

            return None

        except Exception as exc:
            logger.exception("Failed to parse Instagram message: %s", exc)
            return None

    def validate_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Validate Instagram webhook signature.

        Instagram uses HMAC-SHA256 signature in the X-Hub-Signature-256 header.
        """
        if not self._app_secret:
            logger.warning("App secret not configured, skipping signature validation")
            return True

        signature_header = headers.get("x-hub-signature-256", "")
        if not signature_header.startswith("sha256="):
            logger.warning("Invalid signature format")
            return False

        expected_signature = signature_header[7:]  # Remove "sha256=" prefix
        computed_signature = hmac.new(
            self._app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_signature, computed_signature)

    async def shutdown(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
