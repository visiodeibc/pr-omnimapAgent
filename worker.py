import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from adapters.base import OutgoingMessage, Platform
from adapters.registry import AdapterRegistry
from settings import Settings
from supabase_client import SupabaseRestClient

logger = logging.getLogger(__name__)


class UnifiedWorker:
    """
    Unified polling worker that handles all job types.

    Uses the adapter registry to send messages to the correct platform,
    making the worker platform-agnostic.
    """

    HANDLED_TYPES = ["python_hello", "notify_user", "echo_job"]

    def __init__(self, settings: Settings, adapter_registry: AdapterRegistry) -> None:
        """
        Initialize the worker.

        Args:
            settings: Application settings.
            adapter_registry: Registry of messaging adapters for all platforms.
        """
        self._settings = settings
        self._adapters = adapter_registry
        logger.info("httpx version %s", httpx.__version__)
        self._client = SupabaseRestClient(settings.supabase_url, settings.supabase_key)

    def run_forever(self) -> None:
        """Main worker loop - polls for and processes jobs."""
        logger.info("Starting unified worker loop (handling: %s)", self.HANDLED_TYPES)
        logger.info("Configured platforms: %s", self._adapters.list_platforms())
        while True:
            try:
                claimed = self._claim_next_job()
                if not claimed:
                    time.sleep(self._settings.poll_interval)
                    continue
                self._process_job(claimed)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Worker loop error: %s", exc)
                time.sleep(self._settings.poll_interval)

    def _claim_next_job(self) -> Optional[Dict[str, Any]]:
        """Fetch and claim the next available job."""
        try:
            job = self._client.fetch_next_job(self.HANDLED_TYPES)
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch next job: %s", exc)
            return None
        if not job:
            return None
        try:
            claimed = self._client.claim_job(job["id"])
        except httpx.HTTPError as exc:
            logger.error("Failed to claim job %s: %s", job["id"], exc)
            return None
        if not claimed:
            return None
        logger.info("Claimed job %s (%s)", claimed["id"], claimed["type"])
        return claimed

    def _process_job(self, job: Dict[str, Any]) -> None:
        """Route job to appropriate processor."""
        job_type = job["type"]
        job_id = job["id"]

        try:
            if job_type == "python_hello":
                self._process_python_hello(job)
            elif job_type == "notify_user":
                self._process_notify_user(job)
            elif job_type == "echo_job":
                self._process_echo_job(job)
            else:
                error_msg = f"Unknown job type: {job_type}"
                logger.error(error_msg)
                self._client.update_job(job_id, {"status": "failed", "error": error_msg})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error processing job %s: %s", job_id, exc)
            self._client.update_job(
                job_id,
                {
                    "status": "failed",
                    "error": str(exc),
                },
            )

    def _get_platform_from_job(self, job: Dict[str, Any]) -> Platform:
        """
        Determine the target platform from job data.

        Checks payload.platform first, then session.platform, defaults to Telegram.
        """
        payload = job.get("payload", {})

        # Check for explicit platform in payload
        platform_str = payload.get("platform")
        if platform_str:
            try:
                return Platform(platform_str.lower())
            except ValueError:
                logger.warning("Unknown platform in job: %s, using Telegram", platform_str)
                return Platform.TELEGRAM

        # Check session for platform info
        session_id = job.get("session_id")
        if session_id:
            try:
                session = self._client.get_session(session_id)
                if session:
                    platform_str = session.get("platform")
                    if platform_str:
                        return Platform(platform_str.lower())
            except Exception as exc:
                logger.warning("Could not fetch session %s: %s", session_id, exc)

        # Default to Telegram (primary platform)
        return Platform.TELEGRAM

    def _send_message(
        self,
        chat_id: str,
        text: str,
        platform: Platform,
        **kwargs: Any,
    ) -> bool:
        """
        Send a message using the appropriate platform adapter.

        Args:
            chat_id: Platform-specific chat/conversation ID.
            text: Message text to send.
            platform: Target platform.
            **kwargs: Additional message options.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        adapter = self._adapters.get(platform)
        if not adapter:
            logger.error("No adapter registered for platform: %s", platform.value)
            return False

        message = OutgoingMessage(
            chat_id=chat_id,
            text=text,
            platform=platform,
            **kwargs,
        )

        # Run async send in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(adapter.send_message(message))
            if not result.success:
                logger.error("Failed to send message: %s", result.error)
            return result.success
        finally:
            loop.close()

    def _process_python_hello(self, job: Dict[str, Any]) -> None:
        """Process python_hello job."""
        session_id = job.get("session_id")
        chat_id = job.get("chat_id")
        job_id = job["id"]
        platform = self._get_platform_from_job(job)

        greeting = (
            f"👋 Hello from the Python worker! Timestamp: {datetime.now(timezone.utc).isoformat()}"
        )

        logger.info(
            "Processing python_hello job %s for %s chat %s",
            job_id,
            platform.value,
            chat_id,
        )

        if session_id:
            self._append_session_memory(session_id, greeting)

        self._client.update_job(
            job_id,
            {
                "status": "completed",
                "result": {"message": greeting},
            },
        )

        # Queue notification job with platform info
        self._client.insert_job(
            {
                "type": "notify_user",
                "chat_id": chat_id,
                "payload": {
                    "message": greeting,
                    "platform": platform.value,
                },
                "status": "queued",
                "session_id": session_id,
                "parent_job_id": job_id,
            }
        )

        logger.info("python_hello job %s completed", job_id)

    def _process_notify_user(self, job: Dict[str, Any]) -> None:
        """Process notify_user job - send message to user on any platform."""
        job_id = job["id"]
        chat_id = job.get("chat_id")
        payload = job.get("payload", {})
        message = payload.get("message")
        platform = self._get_platform_from_job(job)

        if not message:
            error_msg = "notify_user job missing payload.message"
            logger.error(error_msg)
            self._client.update_job(job_id, {"status": "failed", "error": error_msg})
            return

        logger.info(
            "Processing notify_user job %s for %s chat %s",
            job_id,
            platform.value,
            chat_id,
        )

        try:
            kwargs = {}
            parse_mode = payload.get("parse_mode")
            if parse_mode:
                kwargs["parse_mode"] = parse_mode

            success = self._send_message(
                chat_id=str(chat_id),
                text=message,
                platform=platform,
                **kwargs,
            )

            if success:
                self._client.update_job(
                    job_id,
                    {
                        "status": "completed",
                        "result": {
                            "delivered_at": datetime.now(timezone.utc).isoformat(),
                            "platform": platform.value,
                        },
                    },
                )
                logger.info("notify_user job %s completed", job_id)
            else:
                self._client.update_job(
                    job_id,
                    {
                        "status": "failed",
                        "error": f"Failed to deliver message via {platform.value}",
                    },
                )

        except Exception as exc:
            logger.exception("Failed to send message for job %s: %s", job_id, exc)
            self._client.update_job(
                job_id,
                {
                    "status": "failed",
                    "error": str(exc),
                },
            )

    def _process_echo_job(self, job: Dict[str, Any]) -> None:
        """Process echo_job - simple echo test job."""
        job_id = job["id"]
        chat_id = job.get("chat_id")
        payload = job.get("payload", {})
        message = payload.get("message", "")
        platform = self._get_platform_from_job(job)

        logger.info(
            "Processing echo_job %s for %s chat %s",
            job_id,
            platform.value,
            chat_id,
        )

        # Simulate some work
        time.sleep(1)

        try:
            success = self._send_message(
                chat_id=str(chat_id),
                text=f"🔄 Background job completed! Original message: \"{message}\"",
                platform=platform,
            )

            if success:
                self._client.update_job(
                    job_id,
                    {
                        "status": "completed",
                        "result": {
                            "processed_message": message,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "platform": platform.value,
                        },
                    },
                )
                logger.info("echo_job %s completed", job_id)
            else:
                self._client.update_job(
                    job_id,
                    {
                        "status": "failed",
                        "error": f"Failed to deliver echo via {platform.value}",
                    },
                )

        except Exception as exc:
            logger.exception("Failed to process echo_job %s: %s", job_id, exc)
            self._client.update_job(
                job_id,
                {
                    "status": "failed",
                    "error": str(exc),
                },
            )

    def _append_session_memory(self, session_id: str, message: str) -> None:
        """Append a message to session memory."""
        try:
            self._client.insert_session_memory(
                {
                    "session_id": session_id,
                    "role": "assistant",
                    "kind": "message",
                    "content": {"text": message, "source": "python_hello"},
                }
            )
        except httpx.HTTPError as exc:
            logger.warning("Failed to append session memory: %s", exc)
