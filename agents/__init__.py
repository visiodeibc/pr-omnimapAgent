"""
Agentic workflow module for processing incoming messages.

This module provides an AI-powered pipeline for:
1. Classifying incoming messages by content type
2. Extracting structured data from messages
3. Routing to appropriate handler functions

Uses OpenAI function calling for intelligent message classification and routing.
"""

from agents.types import (
    ContentType,
    ExtractedData,
    HandlerResult,
    UnifiedRequest,
)

__all__ = [
    "ContentType",
    "ExtractedData",
    "HandlerResult",
    "UnifiedRequest",
]

# Lazy import to avoid circular dependencies
def get_orchestrator():
    """Get the AgentOrchestrator class (lazy import)."""
    from agents.orchestrator import AgentOrchestrator
    return AgentOrchestrator
