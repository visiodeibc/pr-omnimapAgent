"""
Memory service for managing conversation context.

This module provides functionality for:
1. Loading conversation context from session memories
2. Saving user and assistant messages to memory
3. Building prompt context strings for LLM classification
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from logging_config import get_logger

if TYPE_CHECKING:
    from supabase_client import SupabaseRestClient

logger = get_logger(__name__)


@dataclass
class ConversationContext:
    """
    Represents the conversation context for a session.

    Attributes:
        session_id: The session UUID
        is_new_session: True if this is a fresh session (no prior context)
        recent_messages: List of recent messages (newest first)
        message_count: Total number of messages in context
    """

    session_id: str
    is_new_session: bool
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    message_count: int = 0

    def has_context(self) -> bool:
        """Return True if there is conversation context available."""
        return len(self.recent_messages) > 0 and not self.is_new_session


class MemoryService:
    """
    Service for managing conversation memory.

    Handles loading context from the database and saving new messages.
    """

    # Default number of recent messages to include in context
    DEFAULT_CONTEXT_LIMIT = 20

    def __init__(
        self,
        supabase_client: "SupabaseRestClient",
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
    ) -> None:
        """
        Initialize the memory service.

        Args:
            supabase_client: Supabase REST client for database operations
            context_limit: Maximum number of recent messages to load (default 20)
        """
        self._supabase = supabase_client
        self._context_limit = context_limit

    def load_context(
        self,
        session_id: str,
        is_new_session: bool = False,
    ) -> ConversationContext:
        """
        Load conversation context for a session.

        Args:
            session_id: The session UUID
            is_new_session: Whether this is a new session (skip loading if True)

        Returns:
            ConversationContext with recent messages
        """
        if is_new_session:
            logger.debug(
                "New session, no context to load",
                extra={"session_id": session_id},
            )
            return ConversationContext(
                session_id=session_id,
                is_new_session=True,
                recent_messages=[],
                message_count=0,
            )

        try:
            memories = self._supabase.get_session_memories(
                session_id=session_id,
                limit=self._context_limit,
                include_archived=False,
            )

            # Reverse to get chronological order (oldest first)
            memories.reverse()

            logger.debug(
                "Loaded conversation context",
                extra={
                    "session_id": session_id,
                    "message_count": len(memories),
                },
            )

            return ConversationContext(
                session_id=session_id,
                is_new_session=False,
                recent_messages=memories,
                message_count=len(memories),
            )

        except Exception as exc:
            logger.warning(
                "Failed to load conversation context",
                extra={"session_id": session_id, "error": str(exc)},
            )
            return ConversationContext(
                session_id=session_id,
                is_new_session=True,
                recent_messages=[],
                message_count=0,
            )

    def save_message(
        self,
        session_id: str,
        role: str,
        content: Dict[str, Any],
        kind: str = "message",
    ) -> Optional[Dict[str, Any]]:
        """
        Save a message to session memory.

        Args:
            session_id: The session UUID
            role: Message role ('user' or 'assistant')
            content: Message content as JSON
            kind: Message kind (default 'message')

        Returns:
            The created memory record, or None if failed
        """
        try:
            memory = self._supabase.insert_session_memory({
                "session_id": session_id,
                "role": role,
                "kind": kind,
                "content": content,
                "archived": False,
            })

            logger.debug(
                "Saved message to memory",
                extra={
                    "session_id": session_id,
                    "role": role,
                    "kind": kind,
                },
            )

            return memory

        except Exception as exc:
            logger.warning(
                "Failed to save message to memory",
                extra={
                    "session_id": session_id,
                    "role": role,
                    "error": str(exc),
                },
            )
            return None

    def save_user_message(
        self,
        session_id: str,
        text: str,
        platform: str,
        platform_user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Save a user message to session memory.

        Args:
            session_id: The session UUID
            text: The message text
            platform: Source platform
            platform_user_id: User ID on the platform
            metadata: Optional additional metadata

        Returns:
            The created memory record, or None if failed
        """
        content: Dict[str, Any] = {
            "text": text,
            "platform": platform,
            "platform_user_id": platform_user_id,
        }
        if metadata:
            content["metadata"] = metadata

        return self.save_message(
            session_id=session_id,
            role="user",
            content=content,
            kind="message",
        )

    def save_assistant_message(
        self,
        session_id: str,
        text: str,
        handler_name: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Save an assistant response to session memory.

        Args:
            session_id: The session UUID
            text: The response text
            handler_name: Name of the handler that generated the response
            content_type: Classified content type
            metadata: Optional additional metadata

        Returns:
            The created memory record, or None if failed
        """
        content: Dict[str, Any] = {"text": text}
        if handler_name:
            content["handler_name"] = handler_name
        if content_type:
            content["content_type"] = content_type
        if metadata:
            content["metadata"] = metadata

        return self.save_message(
            session_id=session_id,
            role="assistant",
            content=content,
            kind="message",
        )

    def build_prompt_context(
        self,
        context: ConversationContext,
        max_messages: int = 10,
    ) -> str:
        """
        Build a prompt context string from conversation context.

        Formats recent messages for inclusion in the LLM prompt.

        Args:
            context: The conversation context
            max_messages: Maximum messages to include (default 10)

        Returns:
            Formatted string of conversation history, or empty string if no context
        """
        if not context.has_context():
            return ""

        messages = context.recent_messages[-max_messages:]
        lines: List[str] = []

        for memory in messages:
            role = memory.get("role", "unknown")
            content = memory.get("content", {})

            if isinstance(content, dict):
                text = content.get("text", "")
            else:
                text = str(content)

            if text:
                role_label = "User" if role == "user" else "Assistant"
                lines.append(f"{role_label}: {text}")

        if not lines:
            return ""

        return "\n".join(lines)
