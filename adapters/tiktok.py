"""
TikTok messaging adapter.

Implements the MessagingAdapter interface for TikTok using TikTok's API.
This adapter handles messages sent via TikTok's messaging features.

Setup requirements:
1. Apply for TikTok for Developers access
2. Create an app and request messaging permissions
3. Configure webhook for messages
4. Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_ACCESS_TOKEN in environment

Note: TikTok's messaging API is currently limited. This adapter is a scaffold
that will be expanded as the API becomes more available.

Reference: https://developers.tiktok.com/doc/tiktok-api-v2-overview
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

# TikTok API base URL
TIKTOK_API_URL = "https://open.tiktokapis.com/v2"


class TikTokAdapter(MessagingAdapter):
    """
    TikTok messaging adapter.

    Handles sending messages to TikTok users via TikTok's API.

    Note: TikTok's direct messaging API has limited availability.
    This implementation uses the available endpoints and will be
    expanded as more features become available.
    """

    def __init__(
        self,
        client_key: str,
        client_secret: str,
        access_token: Optional[str] = None,
    ) -> None:
        """
        Initialize the TikTok adapter.

        Args:
            client_key: TikTok app client key.
            client_secret: TikTok app client secret.
            access_token: User access token for API calls.
        """
        self._client_key = client_key
        self._client_secret = client_secret
        self._access_token = access_token
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def platform(self) -> Platform:
        return Platform.TIKTOK

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_buttons=False,  # TikTok doesn't support inline buttons yet
            supports_markdown=False,
            supports_html=False,
            supports_media=True,
            supports_replies=False,
            supports_editing=False,
            supports_deletion=False,
            max_message_length=1000,
            supported_media_types=["video"],
        )

    async def send_message(self, message: OutgoingMessage) -> MessageDeliveryResult:
        """
        Send a message to a TikTok user.

        Note: TikTok's messaging capabilities are limited. This implementation
        provides a scaffold that can be expanded as the API evolves.
        """
        try:
            # TikTok's current API doesn't have a direct messaging endpoint
            # for third-party apps in the same way Telegram or Instagram do.
            #
            # Options for communication:
            # 1. Comment on videos (if the app has video.comment scope)
            # 2. Use webhooks to receive messages and respond via other channels
            # 3. Future: Direct messaging when available

            # For now, we'll log the intent and return a placeholder response
            logger.info(
                "TikTok message send requested to %s: %s",
                message.chat_id,
                message.text[:50] + "..." if len(message.text) > 50 else message.text,
            )

            # Placeholder for future implementation
            # When TikTok enables direct messaging API, implement here:
            #
            # url = f"{TIKTOK_API_URL}/messages/send/"
            # headers = {"Authorization": f"Bearer {self._access_token}"}
            # payload = {
            #     "recipient_id": message.chat_id,
            #     "message": {"text": message.text},
            # }
            # response = await self._client.post(url, headers=headers, json=payload)

            return MessageDeliveryResult(
                success=False,
                error="TikTok direct messaging not yet implemented",
                error_code="NOT_IMPLEMENTED",
                metadata={
                    "note": "TikTok DM API is limited. Messages logged for alternative delivery.",
                    "intended_recipient": message.chat_id,
                    "message_preview": message.text[:100],
                },
            )

        except Exception as exc:
            logger.exception("Failed to send TikTok message: %s", exc)
            return MessageDeliveryResult(
                success=False,
                error=str(exc),
            )

    def parse_incoming(self, raw_payload: Dict[str, Any]) -> Optional[IncomingMessage]:
        """
        Parse a TikTok webhook payload into an IncomingMessage.

        TikTok webhooks can notify about:
        - Video comments
        - Direct messages (when available)
        - Follow events
        - Other interactions
        """
        try:
            event_type = raw_payload.get("event")

            # Handle comment events
            if event_type == "comment":
                data = raw_payload.get("data", {})
                comment = data.get("comment", {})
                user_data = data.get("user", {})

                user = UserInfo(
                    platform_user_id=str(user_data.get("open_id", "")),
                    username=user_data.get("display_name"),
                    metadata={"avatar_url": user_data.get("avatar_url")},
                )

                chat = ChatInfo(
                    platform_chat_id=str(data.get("video_id", "")),
                    chat_type="comment",
                    metadata={"video_id": data.get("video_id")},
                )

                timestamp = None
                ts = comment.get("create_time")
                if ts:
                    timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)

                return IncomingMessage(
                    platform=Platform.TIKTOK,
                    message_id=str(comment.get("comment_id", "")),
                    user=user,
                    chat=chat,
                    text=comment.get("text"),
                    timestamp=timestamp,
                    raw_payload=raw_payload,
                    metadata={"event_type": "comment"},
                )

            # Handle direct message events (future)
            if event_type == "direct_message":
                data = raw_payload.get("data", {})
                message = data.get("message", {})
                sender = data.get("sender", {})

                user = UserInfo(
                    platform_user_id=str(sender.get("open_id", "")),
                    username=sender.get("display_name"),
                )

                chat = ChatInfo(
                    platform_chat_id=str(sender.get("open_id", "")),
                    chat_type="private",
                )

                return IncomingMessage(
                    platform=Platform.TIKTOK,
                    message_id=str(message.get("message_id", "")),
                    user=user,
                    chat=chat,
                    text=message.get("text"),
                    raw_payload=raw_payload,
                    metadata={"event_type": "direct_message"},
                )

            logger.debug("Unhandled TikTok event type: %s", event_type)
            return None

        except Exception as exc:
            logger.exception("Failed to parse TikTok message: %s", exc)
            return None

    def validate_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Validate TikTok webhook signature.

        TikTok uses HMAC-SHA256 signature validation.
        """
        signature_header = headers.get("x-tiktok-signature", "")
        if not signature_header:
            logger.warning("No TikTok signature header found")
            return False

        computed_signature = hmac.new(
            self._client_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature_header, computed_signature)

    async def shutdown(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


# Utility function for OAuth flow (future use)
async def get_tiktok_access_token(
    client_key: str,
    client_secret: str,
    auth_code: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    """
    Exchange an authorization code for an access token.

    This is used in the OAuth flow when a user authorizes the app.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TIKTOK_API_URL}/oauth/token/",
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()
