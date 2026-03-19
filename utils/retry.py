"""
Retry utilities for external service calls.

Provides decorators and helper functions for implementing retry logic
with exponential backoff for transient failures.
"""

import asyncio
import functools
import random
from typing import Any, Callable, Optional, Tuple, Type, TypeVar, Union

import httpx

from logging_config import get_logger

logger = get_logger(__name__)

# Type variable for return type preservation
T = TypeVar("T")

# Default retryable exceptions for HTTP calls
DEFAULT_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)

# HTTP status codes that indicate transient failures
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable_http_error(exc: Exception) -> bool:
    """
    Check if an HTTP error is retryable.

    Args:
        exc: The exception to check

    Returns:
        True if the error is retryable (transient)
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, DEFAULT_RETRYABLE_EXCEPTIONS)


def calculate_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> float:
    """
    Calculate exponential backoff delay with optional jitter.

    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap
        jitter: Whether to add random jitter

    Returns:
        Delay in seconds
    """
    delay = min(base_delay * (2**attempt), max_delay)
    if jitter:
        # Add ±25% jitter
        delay = delay * (0.75 + random.random() * 0.5)
    return delay


async def retry_async(
    func: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    **kwargs: Any,
) -> T:
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to call
        *args: Positional arguments for the function
        max_attempts: Maximum number of attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay cap
        retryable_exceptions: Tuple of exception types to retry on
        on_retry: Optional callback called on each retry (exc, attempt)
        **kwargs: Keyword arguments for the function

    Returns:
        Result from the function

    Raises:
        The last exception if all retries fail
    """
    if retryable_exceptions is None:
        retryable_exceptions = DEFAULT_RETRYABLE_EXCEPTIONS

    last_exception: Optional[Exception] = None

    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc

            # HTTPStatusError must always be checked against the status code
            # allowlist, even if the broader HTTPError base class is in
            # retryable_exceptions.  This prevents retrying 401/403/etc.
            if isinstance(exc, httpx.HTTPStatusError):
                is_retryable = is_retryable_http_error(exc)
            else:
                is_retryable = (
                    isinstance(exc, retryable_exceptions)
                    or is_retryable_http_error(exc)
                )

            if not is_retryable or attempt == max_attempts - 1:
                raise

            delay = calculate_backoff(attempt, base_delay, max_delay)

            logger.warning(
                "Retryable error, will retry",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "delay_seconds": round(delay, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            if on_retry:
                on_retry(exc, attempt)

            await asyncio.sleep(delay)

    # Should never reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")


def retry_sync(
    func: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    **kwargs: Any,
) -> T:
    """
    Retry a sync function with exponential backoff.

    Args:
        func: Sync function to call
        *args: Positional arguments for the function
        max_attempts: Maximum number of attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay cap
        retryable_exceptions: Tuple of exception types to retry on
        on_retry: Optional callback called on each retry (exc, attempt)
        **kwargs: Keyword arguments for the function

    Returns:
        Result from the function

    Raises:
        The last exception if all retries fail
    """
    import time

    if retryable_exceptions is None:
        retryable_exceptions = DEFAULT_RETRYABLE_EXCEPTIONS

    last_exception: Optional[Exception] = None

    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc

            if isinstance(exc, httpx.HTTPStatusError):
                is_retryable = is_retryable_http_error(exc)
            else:
                is_retryable = (
                    isinstance(exc, retryable_exceptions)
                    or is_retryable_http_error(exc)
                )

            if not is_retryable or attempt == max_attempts - 1:
                raise

            delay = calculate_backoff(attempt, base_delay, max_delay)

            logger.warning(
                "Retryable error, will retry",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "delay_seconds": round(delay, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            if on_retry:
                on_retry(exc, attempt)

            time.sleep(delay)

    # Should never reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for adding retry logic to async functions.

    Args:
        max_attempts: Maximum number of attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay cap
        retryable_exceptions: Tuple of exception types to retry on

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_async(
                func,
                *args,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                retryable_exceptions=retryable_exceptions,
                **kwargs,
            )

        return wrapper  # type: ignore

    return decorator
