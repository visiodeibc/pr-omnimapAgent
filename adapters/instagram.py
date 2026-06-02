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
import json
from collections import Counter
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
from logging_config import get_logger

logger = get_logger(__name__)

# Instagram Graph API base URL
GRAPH_API_URL = "https://graph.facebook.com/v24.0"


def _extract_graph_error(payload: str) -> Dict[str, Any]:
    """Best-effort extraction of Graph API error payload."""
    try:
        data = json.loads(payload)
    except Exception:
        return {}
    if isinstance(data, dict):
        error = data.get("error")
        return error if isinstance(error, dict) else {}
    return {}


def _is_valid_instagram_account_id(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.isdigit()


def _mask_id(value: Optional[str]) -> str:
    if not value:
        return ""
    return value[-4:]


def _is_page_access_token(token: str) -> bool:
    """Check whether a token looks like a Facebook Page Access Token.

    IG-scoped tokens (``IGAA…``) are issued by the Instagram API and cannot
    be used with the Graph API ``/messages`` endpoint which requires a Page
    Access Token (typically starting with ``EAA…``).
    """
    return not token.startswith("IGAA")


def _truncate_instagram_text(text: str, max_bytes: int = 1000) -> tuple[str, bool]:
    """Ensure outbound text respects Instagram's 1000-byte UTF-8 limit."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False

    ellipsis = "..."
    budget = max(0, max_bytes - len(ellipsis.encode("utf-8")))
    truncated = encoded[:budget].decode("utf-8", errors="ignore").rstrip()
    candidate = f"{truncated}{ellipsis}" if truncated else ellipsis[:max_bytes]

    while len(candidate.encode("utf-8")) > max_bytes and truncated:
        truncated = truncated[:-1].rstrip()
        candidate = f"{truncated}{ellipsis}" if truncated else ellipsis[:max_bytes]

    return candidate, True


class InstagramAdapter(MessagingAdapter):
    """
    Instagram Messaging adapter using Meta Graph API.

    Handles sending messages to Instagram users via the Instagram Messaging API.

    Reference: https://developers.facebook.com/docs/messenger-platform/instagram
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        app_secret: Optional[str] = None,
        instagram_account_id: Optional[str] = None,
    ) -> None:
        """
        Initialize the Instagram adapter.

        Args:
            access_token: Page access token with Instagram messaging permissions.
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
            metadata_account_id = (
                message.metadata.get("instagram_account_id")
                if isinstance(message.metadata, dict)
                else None
            )
            instagram_account_id = metadata_account_id or self._instagram_account_id
            account_id_source = (
                "message.metadata.instagram_account_id"
                if metadata_account_id
                else "settings.instagram.account_id"
            )

            if not instagram_account_id:
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "Instagram account ID is missing. "
                        "Provide instagram_account_id from webhook recipient.id or set INSTAGRAM_ACCOUNT_ID."
                    ),
                    error_code="MISSING_ACCOUNT_ID",
                )

            if not _is_valid_instagram_account_id(instagram_account_id):
                logger.error(
                    "Invalid Instagram account ID format: source=%s id_suffix=%s",
                    account_id_source,
                    _mask_id(instagram_account_id),
                )
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "Instagram account ID is malformed. "
                        "Expected a numeric Instagram business account ID."
                    ),
                    error_code="INVALID_ACCOUNT_ID",
                )

            if message.chat_id and instagram_account_id == message.chat_id:
                logger.error(
                    "Instagram account ID matches recipient ID: source=%s id_suffix=%s",
                    account_id_source,
                    _mask_id(instagram_account_id),
                )
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "Instagram account ID appears to be the recipient scoped user ID. "
                        "Use the Instagram business account ID (recipient.id from webhook)."
                    ),
                    error_code="INVALID_ACCOUNT_ID",
                )

            if not metadata_account_id:
                logger.warning(
                    "Instagram account ID not provided in message metadata; using configured ID: %s",
                    _mask_id(instagram_account_id),
                )

            access_token = str(self._access_token).strip() if self._access_token else ""
            if not access_token:
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "Instagram access token is missing. "
                        "Set INSTAGRAM_ACCESS_TOKEN with a Facebook Page Access Token."
                    ),
                    error_code="MISSING_ACCESS_TOKEN",
                )
            if not _is_page_access_token(access_token):
                logger.error(
                    "Token for account %s is an IG-scoped token (IGAA…), "
                    "not a Page Access Token. The Graph API /messages endpoint "
                    "requires a Page Access Token (EAA…).",
                    _mask_id(instagram_account_id),
                )
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "The access token for this Instagram account is an IG-scoped token "
                        "(starts with IGAA). The Graph API messaging endpoint requires a "
                        "Facebook Page Access Token (starts with EAA). Update "
                        "INSTAGRAM_ACCESS_TOKEN with the correct Page Access Token."
                    ),
                    error_code="WRONG_TOKEN_TYPE",
                )

            message_text, was_truncated = _truncate_instagram_text(message.text)
            if was_truncated:
                logger.warning(
                    "Instagram text exceeded byte limit; message truncated: original_bytes=%s truncated_bytes=%s recipient_suffix=%s",
                    len(message.text.encode("utf-8")),
                    len(message_text.encode("utf-8")),
                    _mask_id(message.chat_id),
                )

            # Build the message payload
            payload: Dict[str, Any] = {
                "messaging_type": "RESPONSE",
                "recipient": {"id": message.chat_id},
                "message": {"text": message_text},
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

            params = {"access_token": access_token}
            endpoint_attempts = [
                ("me", f"{GRAPH_API_URL}/me/messages"),
                ("account", f"{GRAPH_API_URL}/{instagram_account_id}/messages"),
            ]

            for endpoint_kind, url in endpoint_attempts:
                response = await self._client.post(url, params=params, json=payload)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    error_body = exc.response.text
                    graph_error = _extract_graph_error(error_body)
                    graph_code = str(graph_error.get("code", ""))
                    graph_type = str(graph_error.get("type", ""))
                    graph_message = str(graph_error.get("message", "")) or error_body

                    should_retry_with_account_endpoint = (
                        endpoint_kind == "me"
                        and graph_code == "100"
                        and "Object with ID 'me'" in graph_message
                    )
                    if should_retry_with_account_endpoint:
                        logger.debug(
                            "Instagram API /me/messages unsupported for account %s; "
                            "retrying account-scoped endpoint",
                            _mask_id(instagram_account_id),
                        )
                        continue
                    raise

                data = response.json()
                return MessageDeliveryResult(
                    success=True,
                    message_id=data.get("message_id"),
                    metadata={"recipient_id": data.get("recipient_id")},
                )

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            graph_error = _extract_graph_error(error_body)
            graph_code = str(graph_error.get("code", ""))
            graph_type = str(graph_error.get("type", ""))
            graph_message = str(graph_error.get("message", "")) or error_body

            # Never include query string in logs (contains access_token).
            request_url = str(exc.request.url)
            safe_request_url = request_url.split("?", 1)[0]
            logger.error(
                "Instagram API error: status=%s code=%s type=%s message=%s url=%s",
                exc.response.status_code,
                graph_code or "unknown",
                graph_type or "unknown",
                graph_message,
                safe_request_url,
            )

            if graph_code == "190":
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "Instagram access token is invalid or expired. "
                        "Regenerate the Page Access Token via the Facebook OAuth flow and "
                        "update INSTAGRAM_ACCESS_TOKEN."
                    ),
                    error_code="INVALID_ACCESS_TOKEN",
                )
            if graph_code == "3":
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "Instagram messaging capability is not enabled for this app/account. "
                        "Ensure the app has Instagram Messaging access (advanced/live as needed) "
                        "and that the target account is allowed for the current app mode."
                    ),
                    error_code="INSTAGRAM_CAPABILITY_MISSING",
                )
            if graph_code == "230":
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "The access token is missing Messenger permissions for this Page "
                        "(pages_messaging). Reconnect Facebook/Instagram via OAuth and ensure "
                        "the selected Page has messaging permissions enabled."
                    ),
                    error_code="MISSING_MESSAGING_PERMISSION",
                )
            if graph_code == "100" and "Object with ID 'me'" in graph_message:
                return MessageDeliveryResult(
                    success=False,
                    error=(
                        "The current token cannot send via /me/messages for this account. "
                        "Use the Page Access Token from the connected Facebook Page and ensure "
                        "INSTAGRAM_ACCESS_TOKEN is that Page Access Token."
                    ),
                    error_code="UNSUPPORTED_ME_ENDPOINT",
                )
            return MessageDeliveryResult(
                success=False,
                error=f"HTTP {exc.response.status_code}: {graph_message}",
                error_code=str(exc.response.status_code),
            )
        except Exception as exc:
            logger.exception("Failed to send Instagram message: %s", exc)
            return MessageDeliveryResult(
                success=False,
                error=str(exc),
            )

    def parse_incoming_many(self, raw_payload: Dict[str, Any]) -> list[IncomingMessage]:
        """
        Parse an Instagram webhook payload into zero or more IncomingMessage values.

        A single webhook request can include multiple message/postback events.
        """
        parsed_messages: list[IncomingMessage] = []

        try:
            for msg_event in self._iter_events(raw_payload):
                event_type = self._detect_event_type(msg_event)

                if event_type == "message_echo":
                    # Instagram includes message echoes under "message" subscription.
                    # Skip them to avoid bot self-loop processing.
                    continue

                if event_type == "message":
                    parsed = self._parse_message_event(msg_event, raw_payload)
                    if parsed:
                        parsed.metadata["event_type"] = event_type
                        parsed_messages.append(parsed)
                elif event_type == "postback":
                    parsed = self._parse_postback_event(msg_event, raw_payload)
                    if parsed:
                        parsed.metadata["event_type"] = event_type
                        parsed_messages.append(parsed)

            return parsed_messages

        except Exception as exc:
            logger.exception("Failed to parse Instagram message: %s", exc)
            return []

    def parse_incoming(self, raw_payload: Dict[str, Any]) -> Optional[IncomingMessage]:
        """Parse first processable event from an Instagram webhook payload."""
        parsed_messages = self.parse_incoming_many(raw_payload)
        return parsed_messages[0] if parsed_messages else None

    def summarize_webhook_events(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Summarize webhook events for observability and troubleshooting.

        Returns event type counts and whether at least one processable
        user message/postback exists in this payload.
        """
        event_types: Counter[str] = Counter()
        processable_events = 0
        event_sources: Counter[str] = Counter()

        for msg_event in self._iter_events(raw_payload):
            event_type = self._detect_event_type(msg_event)
            event_types[event_type] += 1
            if "message" in msg_event:
                event_sources["messaging_or_change_message"] += 1
            if "postback" in msg_event:
                event_sources["postback"] += 1
            if event_type in {"message", "postback"}:
                processable_events += 1

        return {
            "event_type_counts": dict(event_types),
            "processable_events": processable_events,
            "has_processable_event": processable_events > 0,
            "event_sources": dict(event_sources),
        }

    def _iter_events(self, raw_payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        """Collect messaging events from known Instagram webhook envelope shapes."""
        events: list[Dict[str, Any]] = []
        entry = raw_payload.get("entry", [])
        if not isinstance(entry, list):
            return events

        for item in entry:
            if not isinstance(item, dict):
                continue

            # Shape 1: entry[].messaging[]
            messaging = item.get("messaging", [])
            if isinstance(messaging, list):
                for event in messaging:
                    if isinstance(event, dict):
                        events.append(event)

            # Shape 2: entry[].changes[].value
            changes = item.get("changes", [])
            if isinstance(changes, list):
                for change in changes:
                    if not isinstance(change, dict):
                        continue
                    value = change.get("value")
                    if isinstance(value, dict):
                        events.append(value)

        return events

    def _detect_event_type(self, msg_event: Dict[str, Any]) -> str:
        """Detect event type from Messenger-style webhook event object."""
        message = msg_event.get("message")
        if isinstance(message, dict):
            if message.get("is_echo"):
                return "message_echo"
            return "message"

        known_non_message_keys = (
            "read",
            "delivery",
            "reaction",
            "postback",
            "referral",
            "optin",
            "standby",
            "account_linking",
            "request_thread_control",
            "take_thread_control",
            "pass_thread_control",
        )
        for key in known_non_message_keys:
            if key in msg_event:
                return key

        return "unknown"

    def _parse_message_event(
        self, msg_event: Dict[str, Any], raw_payload: Dict[str, Any]
    ) -> Optional[IncomingMessage]:
        """Parse one message event regardless of webhook envelope shape."""
        message = msg_event.get("message")
        if not isinstance(message, dict):
            return None
        if message.get("is_echo"):
            return None

        sender = msg_event.get("sender", {})
        recipient = msg_event.get("recipient", {})

        sender_id = str(sender.get("id", ""))
        if not sender_id:
            return None

        user = UserInfo(
            platform_user_id=sender_id,
            metadata={"instagram_scoped_id": sender.get("id")},
        )

        chat = ChatInfo(
            platform_chat_id=sender_id,
            chat_type="private",
            metadata={"recipient_id": recipient.get("id")},
        )

        text = message.get("text")

        media_urls = []
        media_type = None
        shared_attachment: Optional[Dict[str, Any]] = None
        attachments = message.get("attachments", [])
        for att in attachments:
            att_type = att.get("type")
            payload = att.get("payload", {}) or {}
            if att_type == "image":
                media_type = "image"
                media_urls.append(payload.get("url", ""))
            elif att_type == "video":
                media_type = "video"
                media_urls.append(payload.get("url", ""))
            elif att_type == "audio":
                media_type = "audio"
                media_urls.append(payload.get("url", ""))
            elif att_type == "file":
                media_type = "file"
                media_urls.append(payload.get("url", ""))
            elif att_type in ("ig_reel", "share", "story_mention", "story_reply") and shared_attachment is None:
                shared_attachment = {
                    "type": att_type,
                    "url": payload.get("url"),
                    "title": payload.get("title"),
                    "reel_video_url": payload.get("reel_video_url"),
                    "story_id": payload.get("id"),
                }

        metadata: Dict[str, Any] = {}
        if shared_attachment:
            metadata["instagram_share"] = shared_attachment
            # Surface the share URL as text so the orchestrator classifies this
            # message as an Instagram link and routes it to handle_instagram_link.
            share_url = shared_attachment.get("url")
            if share_url and not text:
                text = share_url

        # Ignore message events that have no user content.
        if not text and not media_urls and not shared_attachment:
            return None

        timestamp = self._parse_timestamp(msg_event.get("timestamp"))

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
            metadata=metadata,
        )

    def _parse_postback_event(
        self, msg_event: Dict[str, Any], raw_payload: Dict[str, Any]
    ) -> Optional[IncomingMessage]:
        """Parse postback event into IncomingMessage."""
        postback = msg_event.get("postback")
        if not isinstance(postback, dict):
            return None

        sender = msg_event.get("sender", {})
        recipient = msg_event.get("recipient", {})
        sender_id = str(sender.get("id", ""))
        if not sender_id:
            return None

        payload = postback.get("payload")
        title = postback.get("title")
        text = str(payload or title or "").strip()
        if not text:
            text = "[postback]"

        timestamp = self._parse_timestamp(msg_event.get("timestamp"))

        return IncomingMessage(
            platform=Platform.INSTAGRAM,
            message_id=str(postback.get("mid") or ""),
            user=UserInfo(
                platform_user_id=sender_id,
                metadata={"instagram_scoped_id": sender.get("id")},
            ),
            chat=ChatInfo(
                platform_chat_id=sender_id,
                chat_type="private",
                metadata={"recipient_id": recipient.get("id")},
            ),
            text=text,
            timestamp=timestamp,
            raw_payload=raw_payload,
            metadata={"postback_payload": payload, "postback_title": title},
        )

    @staticmethod
    def _parse_timestamp(raw_timestamp: Any) -> Optional[datetime]:
        """Parse webhook timestamp in milliseconds, accepting str/int formats."""
        if raw_timestamp in (None, ""):
            return None

        try:
            timestamp_ms = int(raw_timestamp)
        except (TypeError, ValueError):
            logger.debug("Invalid Instagram timestamp value: %s", raw_timestamp)
            return None

        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

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
            header_keys = ",".join(sorted(headers.keys()))
            header_preview = signature_header[:32] + "..." if signature_header else ""
            logger.warning(
                "Invalid signature format: header_present=%s header_value=%s header_keys=%s",
                bool(signature_header),
                header_preview,
                header_keys,
            )
            return False

        expected_signature = signature_header[7:]  # Remove "sha256=" prefix
        computed_signature = hmac.new(
            self._app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, computed_signature):
            secret_fingerprint = hashlib.sha256(self._app_secret.encode("utf-8")).hexdigest()[:8]
            logger.error(
                "Invalid Instagram webhook signature: expected_prefix=%s computed_prefix=%s body_length=%s secret_fingerprint=%s",
                expected_signature[:16],
                computed_signature[:16],
                len(body),
                secret_fingerprint,
            )
            return False

        return True

    async def shutdown(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
