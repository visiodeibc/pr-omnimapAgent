"""
Debug Reporter for development logging.

This module provides a DebugReporter class that collects processing logs
and sends them back to the user via their chat platform in development mode.

Usage:
    reporter = DebugReporter(
        chat_id="12345",
        platform=Platform.TELEGRAM,
        adapter_registry=registry,
        enabled=True,  # Typically: settings.environment != "production"
    )

    reporter.log("Starting processing")
    reporter.log("Classified as PLACE_NAME", level="info")
    reporter.log("Error occurred", level="error", data={"error": str(e)})

    await reporter.flush()  # Send all collected logs to user
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from logging_config import get_logger

if TYPE_CHECKING:
    from adapters.base import Platform
    from adapters.registry import AdapterRegistry

logger = get_logger(__name__)


class DebugLevel(str, Enum):
    """Debug log levels with emoji prefixes for Telegram."""

    DEBUG = "debug"
    INFO = "info"
    STEP = "step"  # For pipeline steps
    WARN = "warn"
    ERROR = "error"
    SUCCESS = "success"

    @property
    def emoji(self) -> str:
        """Get emoji for this log level."""
        return {
            DebugLevel.DEBUG: "🔍",
            DebugLevel.INFO: "ℹ️",
            DebugLevel.STEP: "▶️",
            DebugLevel.WARN: "⚠️",
            DebugLevel.ERROR: "❌",
            DebugLevel.SUCCESS: "✅",
        }.get(self, "•")


@dataclass
class DebugEntry:
    """A single debug log entry."""

    message: str
    level: DebugLevel
    timestamp: datetime
    data: Optional[Dict[str, Any]] = None

    def format(self, include_timestamp: bool = True) -> str:
        """Format the entry for display (plain text, no Markdown)."""
        parts = []

        if include_timestamp:
            time_str = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
            parts.append(f"[{time_str}]")

        parts.append(f"{self.level.emoji}")
        parts.append(self.message)

        line = " ".join(parts)

        # Add data on new line if present
        if self.data:
            # Format data as key: value pairs
            data_lines = []
            for key, value in self.data.items():
                # Truncate long values
                str_value = str(value)
                if len(str_value) > 100:
                    str_value = str_value[:97] + "..."
                data_lines.append(f"  • {key}: {str_value}")
            if data_lines:
                line += "\n" + "\n".join(data_lines)

        return line


@dataclass
class DebugReporter:
    """
    Collects debug logs during message processing and reports them to the user.

    Only active when enabled=True (typically in development mode).
    Logs are collected during processing and can be flushed to the user's chat.
    """

    chat_id: str
    platform: "Platform"
    adapter_registry: "AdapterRegistry"
    enabled: bool = True

    # Configuration
    max_entries: int = 50  # Prevent runaway logging
    max_message_length: int = 4000  # Telegram limit is 4096
    include_timestamps: bool = True
    header: str = "🔧 Debug Log\n"

    # Internal state
    _entries: List[DebugEntry] = field(default_factory=list)
    _start_time: Optional[datetime] = field(default=None)

    def __post_init__(self) -> None:
        """Initialize the reporter."""
        if self.enabled:
            self._start_time = datetime.now(timezone.utc)
            logger.debug(
                "DebugReporter initialized",
                extra={"chat_id": self.chat_id, "platform": self.platform.value},
            )

    def log(
        self,
        message: str,
        level: str = "info",
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a debug log entry.

        Args:
            message: The log message
            level: Log level (debug, info, step, warn, error, success)
            data: Optional structured data to include
        """
        if not self.enabled:
            return

        if len(self._entries) >= self.max_entries:
            logger.warning("DebugReporter max entries reached, dropping log")
            return

        try:
            debug_level = DebugLevel(level.lower())
        except ValueError:
            debug_level = DebugLevel.INFO

        entry = DebugEntry(
            message=message,
            level=debug_level,
            timestamp=datetime.now(timezone.utc),
            data=data,
        )
        self._entries.append(entry)

        # Also log to standard logger at debug level
        logger.debug(
            f"[DebugReporter] {message}",
            extra={"level": level, "data": data},
        )

    def step(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log a pipeline step."""
        self.log(message, level="step", data=data)

    def info(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log an info message."""
        self.log(message, level="info", data=data)

    def debug(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log a debug message."""
        self.log(message, level="debug", data=data)

    def warn(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log a warning."""
        self.log(message, level="warn", data=data)

    def error(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log an error."""
        self.log(message, level="error", data=data)

    def success(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log a success message."""
        self.log(message, level="success", data=data)

    def format_report(self) -> str:
        """Format all collected entries into a report string."""
        if not self._entries:
            return ""

        lines = [self.header]

        # Add duration if we have a start time
        if self._start_time:
            duration = datetime.now(timezone.utc) - self._start_time
            duration_ms = int(duration.total_seconds() * 1000)
            lines.append(f"⏱️ Duration: {duration_ms}ms\n")

        lines.append("───────────────────")

        for entry in self._entries:
            lines.append(entry.format(include_timestamp=self.include_timestamps))

        lines.append("───────────────────")
        lines.append(f"📊 {len(self._entries)} log entries")

        report = "\n".join(lines)

        # Truncate if too long
        if len(report) > self.max_message_length:
            report = report[: self.max_message_length - 20] + "\n\n... (truncated)"

        return report

    async def flush(self) -> bool:
        """
        Send all collected logs to the user's chat.

        Returns:
            True if logs were sent successfully, False otherwise
        """
        if not self.enabled or not self._entries:
            return True

        report = self.format_report()
        if not report:
            return True

        try:
            from adapters.base import OutgoingMessage

            adapter = self.adapter_registry.get(self.platform)
            if not adapter:
                logger.warning(
                    "No adapter available for debug report",
                    extra={"platform": self.platform.value},
                )
                return False

            message = OutgoingMessage(
                chat_id=self.chat_id,
                text=report,
                platform=self.platform,
                # No parse_mode - send as plain text to avoid Markdown parsing errors
                # with dynamic content containing special characters
            )

            result = await adapter.send_message(message)

            if not result.success:
                logger.warning(
                    "Failed to send debug report",
                    extra={"error": result.error},
                )
                return False

            logger.debug(
                "Debug report sent",
                extra={"chat_id": self.chat_id, "entries": len(self._entries)},
            )

            # Clear entries after successful send
            self._entries.clear()
            return True

        except Exception as exc:
            logger.exception("Error flushing debug report", extra={"error": str(exc)})
            return False

    async def flush_if_needed(self, threshold: int = 20) -> bool:
        """
        Flush logs if entry count exceeds threshold.

        Useful for long-running operations to send intermediate reports.

        Args:
            threshold: Number of entries that triggers a flush

        Returns:
            True if flush was successful or not needed
        """
        if len(self._entries) >= threshold:
            return await self.flush()
        return True

    def clear(self) -> None:
        """Clear all collected entries without sending."""
        self._entries.clear()
        self._start_time = datetime.now(timezone.utc)


def create_debug_reporter(
    chat_id: str,
    platform: "Platform",
    adapter_registry: "AdapterRegistry",
    environment: str,
) -> DebugReporter:
    """
    Factory function to create a DebugReporter.

    Automatically enables/disables based on environment.

    Args:
        chat_id: Target chat for debug messages
        platform: Platform to send messages on
        adapter_registry: Registry to get the appropriate adapter
        environment: Current environment (local, staging, production)

    Returns:
        Configured DebugReporter instance
    """
    enabled = environment not in ("production", "prod")

    return DebugReporter(
        chat_id=chat_id,
        platform=platform,
        adapter_registry=adapter_registry,
        enabled=enabled,
    )
