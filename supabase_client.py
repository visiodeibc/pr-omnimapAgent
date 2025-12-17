import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> dt.datetime:
    """Parse ISO datetime string to timezone-aware datetime object."""
    # Handle various ISO formats
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(iso_str)
    # Ensure timezone-aware (assume UTC if naive)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


class SupabaseRestClient:
    def __init__(self, supabase_url: str, service_key: str) -> None:
        base = supabase_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{base}/rest/v1",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_next_job(self, job_types: Iterable[str]) -> Optional[Dict[str, Any]]:
        if not job_types:
            return None
        params = {
            "status": "eq.queued",
            "type": f"in.({','.join(job_types)})",
            "order": "created_at.asc",
            "limit": "1",
        }
        resp = self._client.get("/jobs", params=params)
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        if not data:
            return None
        return data[0]

    def claim_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        params = {
            "id": f"eq.{job_id}",
            "status": "eq.queued",
        }
        payload = {
            "status": "processing",
            "updated_at": _now_iso(),
        }
        resp = self._client.patch(
            "/jobs",
            params=params,
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        if not data:
            return None
        return data[0]

    def update_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        params = {"id": f"eq.{job_id}"}
        payload = {**payload, "updated_at": _now_iso()}
        resp = self._client.patch(
            "/jobs",
            params=params,
            json=payload,
        )
        resp.raise_for_status()

    def insert_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._client.post(
            "/jobs",
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        return data[0]

    def insert_session_memory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new session memory record."""
        resp = self._client.post(
            "/session_memories",
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        return data[0] if data else {}

    def get_session_memories(
        self,
        session_id: str,
        limit: int = 20,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent memories for a session.

        Args:
            session_id: The session UUID
            limit: Maximum number of memories to return (default 20)
            include_archived: Whether to include archived memories (default False)

        Returns:
            List of memory records, ordered by created_at descending (newest first)
        """
        params: Dict[str, str] = {
            "session_id": f"eq.{session_id}",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        if not include_archived:
            params["archived"] = "eq.false"

        resp = self._client.get("/session_memories", params=params)
        resp.raise_for_status()
        return resp.json()

    def archive_session_memories(self, session_id: str) -> int:
        """
        Mark all non-archived memories for a session as archived.

        Used when a session expires (30+ minutes of inactivity).

        Args:
            session_id: The session UUID

        Returns:
            Number of memories archived
        """
        params = {
            "session_id": f"eq.{session_id}",
            "archived": "eq.false",
        }
        payload = {"archived": True}
        resp = self._client.patch(
            "/session_memories",
            params=params,
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        return len(data)

    def get_or_create_active_session(
        self,
        platform: str,
        platform_user_id: str,
        platform_chat_id: Optional[int] = None,
        inactivity_threshold_minutes: int = 30,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Get an active session or create a new one.

        If the existing session has been inactive for longer than the threshold,
        archives old memories and resets the session context.

        Args:
            platform: Platform identifier (telegram, instagram, etc.)
            platform_user_id: User ID on the platform
            platform_chat_id: Optional chat ID
            inactivity_threshold_minutes: Minutes of inactivity before session expires (default 30)
            metadata: Optional metadata to store with session

        Returns:
            Tuple of (session_dict, is_new_session)
            - is_new_session is True if this is a fresh session (no prior context)
        """
        now = dt.datetime.now(dt.timezone.utc)
        now_iso = now.isoformat()

        # First, try to get existing session
        params = {
            "platform": f"eq.{platform}",
            "platform_user_id": f"eq.{platform_user_id}",
            "limit": "1",
        }
        resp = self._client.get("/sessions", params=params)
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()

        if data:
            # Existing session found - check if it's still active
            session = data[0]
            last_message_at_str = session.get("last_message_at")

            is_new_session = False
            if last_message_at_str:
                last_message_at = _parse_iso(last_message_at_str)
                time_since_last = now - last_message_at
                threshold = dt.timedelta(minutes=inactivity_threshold_minutes)

                if time_since_last > threshold:
                    # Session expired - archive old memories
                    self.archive_session_memories(session["id"])
                    is_new_session = True

            # Update last_message_at
            update_payload: Dict[str, Any] = {
                "last_message_at": now_iso,
                "updated_at": now_iso,
            }
            if platform_chat_id is not None:
                update_payload["platform_chat_id"] = platform_chat_id
            if metadata:
                update_payload["metadata"] = metadata

            update_params = {"id": f"eq.{session['id']}"}
            update_resp = self._client.patch(
                "/sessions",
                params=update_params,
                json=update_payload,
                headers={"Prefer": "return=representation"},
            )
            update_resp.raise_for_status()
            updated_data: List[Dict[str, Any]] = update_resp.json()
            return (updated_data[0] if updated_data else session, is_new_session)

        # No existing session - create new one
        create_payload: Dict[str, Any] = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "platform_chat_id": platform_chat_id,
            "last_message_at": now_iso,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        if metadata:
            create_payload["metadata"] = metadata

        create_resp = self._client.post(
            "/sessions",
            json=create_payload,
            headers={"Prefer": "return=representation"},
        )
        create_resp.raise_for_status()
        created_data: List[Dict[str, Any]] = create_resp.json()
        return (created_data[0], True)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a session by ID."""
        params = {
            "id": f"eq.{session_id}",
            "limit": "1",
        }
        resp = self._client.get("/sessions", params=params)
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        if not data:
            return None
        return data[0]

    def ensure_session(
        self,
        platform: str,
        platform_user_id: str,
        platform_chat_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Ensure a session exists for a given platform user (upsert)."""
        now = _now_iso()
        payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "platform_chat_id": platform_chat_id,
            "last_message_at": now,
            "updated_at": now,
        }
        if metadata:
            payload["metadata"] = metadata

        params = {
            "on_conflict": "platform,platform_user_id",
        }
        resp = self._client.post(
            "/sessions",
            json=payload,
            params=params,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        if not data:
            return None
        return data[0]

    # =========================================================================
    # Incoming Request Operations (for agentic workflow)
    # =========================================================================

    def insert_incoming_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new incoming request record."""
        resp = self._client.post(
            "/incoming_requests",
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        return data[0] if data else {}

    def update_incoming_request(
        self, request_id: str, payload: Dict[str, Any]
    ) -> None:
        """Update an incoming request record."""
        params = {"id": f"eq.{request_id}"}
        payload = {**payload, "updated_at": _now_iso()}
        resp = self._client.patch(
            "/incoming_requests",
            params=params,
            json=payload,
        )
        resp.raise_for_status()

    def get_incoming_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Fetch an incoming request by ID."""
        params = {
            "id": f"eq.{request_id}",
            "limit": "1",
        }
        resp = self._client.get("/incoming_requests", params=params)
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        if not data:
            return None
        return data[0]

    def fetch_pending_requests(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch pending incoming requests for processing."""
        params = {
            "status": "eq.queued",
            "order": "created_at.asc",
            "limit": str(limit),
        }
        resp = self._client.get("/incoming_requests", params=params)
        resp.raise_for_status()
        return resp.json()
