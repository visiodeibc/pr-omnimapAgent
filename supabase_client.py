import datetime as dt
from typing import Any, Dict, Iterable, List, Optional

import httpx


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


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

    def insert_session_memory(self, payload: Dict[str, Any]) -> None:
        resp = self._client.post(
            "/session_memories",
            json=payload,
        )
        resp.raise_for_status()

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
