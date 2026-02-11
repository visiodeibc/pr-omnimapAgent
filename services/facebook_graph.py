"""
Facebook Graph API helpers for OAuth and Page subscriptions.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from logging_config import get_logger
from utils.retry import retry_async

logger = get_logger(__name__)

DEFAULT_LOGIN_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_manage_metadata,instagram_manage_messages"
)
DEFAULT_GRAPH_API_VERSION = "v24.0"


def build_oauth_url(
    app_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = DEFAULT_LOGIN_SCOPES,
    graph_api_version: str = DEFAULT_GRAPH_API_VERSION,
) -> str:
    """Build the Facebook OAuth dialog URL."""
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": scopes,
    }
    return f"https://www.facebook.com/{graph_api_version}/dialog/oauth?{urlencode(params)}"


@dataclass
class FacebookPageInfo:
    id: str
    name: Optional[str]
    access_token: Optional[str]

    @classmethod
    def from_graph(cls, data: Dict[str, Any]) -> "FacebookPageInfo":
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name"),
            access_token=data.get("access_token"),
        )

    def to_dict(self, include_access_token: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": self.id, "name": self.name}
        if include_access_token and self.access_token:
            payload["access_token"] = self.access_token
        return payload


class FacebookGraphClient:
    """Async client wrapper for Facebook Graph API calls."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        graph_api_version: str = DEFAULT_GRAPH_API_VERSION,
        timeout: float = 30.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = f"https://graph.facebook.com/{graph_api_version}"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "FacebookGraphClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"

        async def _do_request() -> httpx.Response:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

        return await retry_async(_do_request, max_attempts=3, base_delay=1.0)

    async def exchange_code_for_user_token(
        self,
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        params = {
            "client_id": self._app_id,
            "client_secret": self._app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        response = await self._request("GET", "/oauth/access_token", params=params)
        return response.json()

    async def get_pages(self, user_access_token: str) -> List[FacebookPageInfo]:
        params = {"access_token": user_access_token}
        response = await self._request("GET", "/me/accounts", params=params)
        data = response.json()
        pages = data.get("data", [])
        return [FacebookPageInfo.from_graph(page) for page in pages]

    async def get_instagram_business_id(
        self,
        page_id: str,
        page_access_token: str,
    ) -> Optional[str]:
        params = {
            "fields": "instagram_business_account",
            "access_token": page_access_token,
        }
        response = await self._request("GET", f"/{page_id}", params=params)
        data = response.json()
        instagram_data = data.get("instagram_business_account") or {}
        instagram_id = instagram_data.get("id")
        return str(instagram_id) if instagram_id else None

    async def subscribe_page(
        self,
        page_id: str,
        page_access_token: str,
        subscribed_fields: str,
    ) -> Dict[str, Any]:
        params = {
            "subscribed_fields": subscribed_fields,
            "access_token": page_access_token,
        }
        response = await self._request("POST", f"/{page_id}/subscribed_apps", params=params)
        return response.json()
