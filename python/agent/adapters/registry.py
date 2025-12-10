"""
Adapter registry for managing platform messaging adapters.

The registry provides centralized access to all configured adapters,
enabling the worker to route messages to the correct platform.
"""

import logging
from typing import Dict, Optional, Type

from adapters.base import MessagingAdapter, Platform

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Central registry for messaging adapters.

    Provides methods to register, retrieve, and manage platform adapters.
    Supports lazy initialization of adapters based on configuration.
    """

    def __init__(self) -> None:
        self._adapters: Dict[Platform, MessagingAdapter] = {}
        self._adapter_classes: Dict[Platform, Type[MessagingAdapter]] = {}

    def register(self, adapter: MessagingAdapter) -> None:
        """
        Register an initialized adapter instance.

        Args:
            adapter: The adapter instance to register.
        """
        platform = adapter.platform
        self._adapters[platform] = adapter
        logger.info("Registered adapter for platform: %s", platform.value)

    def register_class(
        self,
        platform: Platform,
        adapter_class: Type[MessagingAdapter],
    ) -> None:
        """
        Register an adapter class for lazy initialization.

        Args:
            platform: The platform this adapter handles.
            adapter_class: The adapter class to instantiate when needed.
        """
        self._adapter_classes[platform] = adapter_class

    def get(self, platform: Platform) -> Optional[MessagingAdapter]:
        """
        Get an adapter for the specified platform.

        Args:
            platform: The platform to get an adapter for.

        Returns:
            The adapter instance, or None if not registered.
        """
        return self._adapters.get(platform)

    def get_by_name(self, platform_name: str) -> Optional[MessagingAdapter]:
        """
        Get an adapter by platform name string.

        Args:
            platform_name: The platform name (e.g., "telegram", "instagram").

        Returns:
            The adapter instance, or None if not found.
        """
        try:
            platform = Platform(platform_name.lower())
            return self.get(platform)
        except ValueError:
            logger.warning("Unknown platform: %s", platform_name)
            return None

    def has(self, platform: Platform) -> bool:
        """Check if an adapter is registered for the platform."""
        return platform in self._adapters

    def list_platforms(self) -> list[Platform]:
        """List all registered platforms."""
        return list(self._adapters.keys())

    async def initialize_all(self) -> None:
        """Initialize all registered adapters."""
        for platform, adapter in self._adapters.items():
            try:
                await adapter.initialize()
                logger.info("Initialized adapter: %s", platform.value)
            except Exception as exc:
                logger.error("Failed to initialize %s adapter: %s", platform.value, exc)

    async def shutdown_all(self) -> None:
        """Shutdown all registered adapters."""
        for platform, adapter in self._adapters.items():
            try:
                await adapter.shutdown()
                logger.info("Shut down adapter: %s", platform.value)
            except Exception as exc:
                logger.error("Failed to shutdown %s adapter: %s", platform.value, exc)


# Global registry instance
_registry: Optional[AdapterRegistry] = None


def get_adapter_registry() -> AdapterRegistry:
    """Get the global adapter registry instance."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry  # noqa: PLW0603
    _registry = None
