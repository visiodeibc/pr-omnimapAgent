"""
Logging configuration for local and production environments.

This module provides structured logging with different formats and levels
based on the environment (local development vs production).
"""

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# JSON formatting for production
try:
    import json
except ImportError:
    json = None  # type: ignore


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in production.

    Outputs logs as single-line JSON objects for easy parsing by
    log aggregation services (CloudWatch, Stackdriver, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "taskName",
                "message",
            ):
                log_data[key] = value

        return json.dumps(log_data)


class LocalFormatter(logging.Formatter):
    """
    Human-readable formatter for local development.

    Provides colorized output with clear formatting for easy debugging.
    """

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Add color to level name in local mode
        color = self.COLORS.get(record.levelname, "")
        levelname = f"{color}{record.levelname:8}{self.RESET}" if color else record.levelname

        # Format timestamp
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Build the log line
        message = record.getMessage()
        base = f"{timestamp} | {levelname} | {record.name:25} | {message}"

        # Add exception info if present
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"

        return base


def get_environment() -> str:
    """
    Determine the current environment.

    Returns:
        'production', 'staging', or 'local'
    """
    env = os.getenv("ENVIRONMENT", os.getenv("ENV", "local")).lower()
    if env in ("production", "prod"):
        return "production"
    if env in ("staging", "stage"):
        return "staging"
    return "local"


def get_log_level() -> int:
    """
    Get the logging level from environment.

    Returns:
        Logging level constant (e.g., logging.INFO)
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def setup_logging(
    level: Optional[int] = None,
    environment: Optional[str] = None,
    json_logs: Optional[bool] = None,
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Override log level (defaults to LOG_LEVEL env var or INFO)
        environment: Override environment (defaults to ENVIRONMENT env var)
        json_logs: Force JSON logging on/off (defaults to True in production)
    """
    if level is None:
        level = get_log_level()

    if environment is None:
        environment = get_environment()

    # Determine if we should use JSON formatting
    if json_logs is None:
        json_logs = environment in ("production", "staging")

    # Create root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Set formatter based on environment
    if json_logs:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(LocalFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Set library log levels to reduce noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # Log startup info
    root_logger.info(
        "Logging configured",
        extra={
            "environment": environment,
            "level": logging.getLevelName(level),
            "json_format": json_logs,
        },
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    This is a convenience wrapper around logging.getLogger that
    ensures consistent logger naming.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LogContext:
    """
    Context manager for adding structured data to log records.

    Usage:
        with LogContext(request_id="abc123", user_id="user456"):
            logger.info("Processing request")  # Will include request_id and user_id
    """

    _context: Dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._old_values: Dict[str, Any] = {}

    def __enter__(self) -> "LogContext":
        for key, value in self._kwargs.items():
            self._old_values[key] = LogContext._context.get(key)
            LogContext._context[key] = value
        return self

    def __exit__(self, *args: Any) -> None:
        for key in self._kwargs:
            if self._old_values[key] is None:
                LogContext._context.pop(key, None)
            else:
                LogContext._context[key] = self._old_values[key]

    @classmethod
    def get_context(cls) -> Dict[str, Any]:
        """Get the current logging context."""
        return cls._context.copy()


class ContextFilter(logging.Filter):
    """
    Logging filter that adds context data to log records.

    This filter should be added to handlers to include LogContext data.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in LogContext.get_context().items():
            setattr(record, key, value)
        return True
