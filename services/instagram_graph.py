"""
Instagram Graph API helpers for fetching post/reel metadata.

Used by the agent to fetch the caption, author, and thumbnail of an Instagram
post or reel when a user shares one (either as a DM attachment or by pasting
the URL) so the agent can reply with a summary.

Strategy (in order, each layer falls back to the next):

1. Resolve the canonical permalink and shortcode from the user-provided URL.
2. Fetch the post's public HTML and parse OpenGraph + Twitter Card meta tags
   to obtain the author username, caption preview, thumbnail, and media type.
   These tags are what Slack/Twitter/Discord unfurl on, so Meta intentionally
   serves them un-authenticated.
3. If a username was resolved AND a Business-Discovery-capable token is
   configured, call ``/{ig_user_id}?fields=business_discovery.username(...)``
   to upgrade the caption preview to the full untruncated caption plus like
   and comment counts. Works for any public Business/Creator account.
4. ``instagram_oembed`` is intentionally not called: it requires the Meta
   ``oEmbed Read`` app review approval, which gates 100% of calls regardless
   of post ownership.

Refs:
- https://developers.facebook.com/docs/instagram-api/guides/business-discovery
- https://developers.facebook.com/docs/instagram-platform/oembed (gated)
"""

import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from logging_config import get_logger
from utils.retry import retry_async

logger = get_logger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v24.0"
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am"}

# Pretend to be a regular desktop browser so IG serves the full OG-tagged HTML
# rather than the bare bot/login-wall shell.
_PUBLIC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)

# How deep to paginate the Business Discovery media list when looking for the
# shared shortcode. 25 items/page; 4 pages covers the most recent 100 posts.
_BD_MAX_PAGES = 4


@dataclass
class IGPostInfo:
    """Public metadata for an Instagram post or reel."""

    permalink: str
    shortcode: Optional[str] = None
    author_name: Optional[str] = None
    author_url: Optional[str] = None
    title: Optional[str] = None  # caption (full when source=business_discovery)
    thumbnail_url: Optional[str] = None
    media_type: Optional[str] = None  # "reel", "post", "tv", "unknown"
    like_count: Optional[int] = None
    comments_count: Optional[int] = None
    timestamp: Optional[str] = None
    source: Optional[str] = None  # "business_discovery" | "og_meta"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "permalink": self.permalink,
            "shortcode": self.shortcode,
            "author_name": self.author_name,
            "author_url": self.author_url,
            "title": self.title,
            "thumbnail_url": self.thumbnail_url,
            "media_type": self.media_type,
            "like_count": self.like_count,
            "comments_count": self.comments_count,
            "timestamp": self.timestamp,
            "source": self.source,
        }


def extract_shortcode(url: str) -> Optional[str]:
    """Extract the post/reel shortcode from an Instagram URL.

    Recognized path shapes: ``/p/<code>/``, ``/reel/<code>/``, ``/reels/<code>/``,
    ``/tv/<code>/``. Also tolerates ``/<username>/reel/<code>/`` etc. that IG
    sometimes serves in ``og:url``. Returns ``None`` if the URL is not a
    recognizable IG link.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    if host not in INSTAGRAM_HOSTS:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    kinds = {"p", "reel", "reels", "tv"}
    for i, part in enumerate(parts):
        if part.lower() in kinds and i + 1 < len(parts):
            return parts[i + 1]
    return None


def canonicalize_permalink(url: str) -> Optional[str]:
    """Return a clean ``https://www.instagram.com/<kind>/<shortcode>/`` URL.

    Strips usernames, query params, and shortened hosts. Both Business Discovery
    and the public OG fetch behave most predictably against canonical permalinks.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    if host not in INSTAGRAM_HOSTS:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    kinds = {"p", "reel", "reels", "tv"}
    for i, part in enumerate(parts):
        kind = part.lower()
        if kind in kinds and i + 1 < len(parts):
            if kind == "reels":
                kind = "reel"
            return f"https://www.instagram.com/{kind}/{parts[i + 1]}/"
    return None


def _infer_media_type(permalink: str) -> str:
    parsed = urlparse(permalink)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return "unknown"
    kind = parts[0].lower()
    if kind in {"reel", "reels"}:
        return "reel"
    if kind == "p":
        return "post"
    if kind == "tv":
        return "tv"
    return "unknown"


def _meta(html_text: str, name: str, kind: str = "property") -> Optional[str]:
    """Pull a single meta-tag content value out of an HTML document."""
    pattern = (
        rf'<meta[^>]+{kind}=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']'
    )
    m = re.search(pattern, html_text)
    if m:
        return html.unescape(m.group(1))
    pattern_rev = (
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{kind}=["\']{re.escape(name)}["\']'
    )
    m = re.search(pattern_rev, html_text)
    if m:
        return html.unescape(m.group(1))
    return None


def _parse_public_meta(html_text: str) -> Optional[Dict[str, Any]]:
    """Extract username, caption preview, counts, thumbnail, media type from IG HTML.

    Returns ``None`` if the page didn't include the OpenGraph tags we rely on
    (e.g. IG served a login-wall shell or an error page).
    """
    og_url = _meta(html_text, "og:url")
    og_title = _meta(html_text, "og:title")
    og_desc = _meta(html_text, "og:description")
    og_image = _meta(html_text, "og:image")
    tw_title = _meta(html_text, "twitter:title", "name")

    if not (og_url or og_desc or tw_title):
        return None

    username = None
    if og_url:
        try:
            parts = [p for p in urlparse(og_url).path.split("/") if p]
            # og:url is typically /<username>/reel/<shortcode>/ for reels by
            # business accounts, or /<kind>/<shortcode>/ for posts without an
            # owner segment.
            if len(parts) >= 3 and parts[1].lower() in {"reel", "p", "tv", "reels"}:
                username = parts[0]
        except Exception:
            username = None
    if not username and tw_title:
        m = re.search(r"\(@([A-Za-z0-9._]+)\)", tw_title)
        if m:
            username = m.group(1)

    like_count: Optional[int] = None
    comments_count: Optional[int] = None
    caption_preview: Optional[str] = None
    if og_desc:
        # Typical shape: "1,022 likes, 2,597 comments - devilhaeyong on May 17, 2026: "...caption..."
        m = re.match(
            r"\s*([\d,]+)\s+likes?,\s+([\d,]+)\s+comments?\s+-\s+\S+\s+on\s+[^:]+:\s+(.*)",
            og_desc,
            flags=re.DOTALL,
        )
        if m:
            try:
                like_count = int(m.group(1).replace(",", ""))
                comments_count = int(m.group(2).replace(",", ""))
            except ValueError:
                like_count = comments_count = None
            caption_preview = m.group(3).strip().strip('"').strip()
        else:
            caption_preview = og_desc.strip()
    if not caption_preview and og_title:
        m = re.search(r":\s*(.*)", og_title, flags=re.DOTALL)
        caption_preview = (m.group(1) if m else og_title).strip().strip('"').strip()

    media_type: Optional[str] = None
    haystack = (tw_title or og_title or "").lower()
    if "reel" in haystack:
        media_type = "reel"
    elif "igtv" in haystack:
        media_type = "tv"
    elif "post" in haystack or "photo" in haystack:
        media_type = "post"

    return {
        "username": username,
        "caption_preview": caption_preview or None,
        "thumbnail_url": og_image,
        "media_type": media_type,
        "like_count": like_count,
        "comments_count": comments_count,
    }


def _bd_media_type(bd_item: Dict[str, Any]) -> Optional[str]:
    raw = (bd_item.get("media_type") or "").upper()
    if not raw:
        return None
    if raw == "VIDEO":
        # Could be a reel or an IGTV video — infer from permalink.
        return _infer_media_type(bd_item.get("permalink") or "")
    if raw in {"IMAGE", "CAROUSEL_ALBUM"}:
        return "post"
    return None


class InstagramGraphService:
    """Async client for fetching Instagram post/reel metadata."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        # Both oEmbed (legacy, gated) and Business Discovery accept the same
        # token shapes: a Page Access Token or "<APP_ID>|<APP_SECRET>".
        if access_token:
            self._token = access_token
        elif app_id and app_secret:
            self._token = f"{app_id}|{app_secret}"
        else:
            self._token = None

        self._ig_user_id = ig_user_id
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def is_configured(self) -> bool:
        # OG-meta scraping needs no credentials; we keep this property as a
        # signal that *some* upgrade beyond the raw URL is possible.
        return True

    @property
    def has_business_discovery(self) -> bool:
        return bool(self._token and self._ig_user_id)

    async def __aenter__(self) -> "InstagramGraphService":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()

    async def fetch_post_info(self, url: str) -> Optional[IGPostInfo]:
        """Fetch public metadata for an Instagram post or reel.

        Returns ``None`` only when nothing useful could be resolved. Errors
        from individual layers are logged and swallowed so the chain can fall
        through to the next layer.
        """
        permalink = canonicalize_permalink(url)
        if not permalink:
            logger.info(
                "URL is not a canonical Instagram permalink",
                extra={"url": url},
            )
            return None

        shortcode = extract_shortcode(permalink)

        og = await self._fetch_public_meta(permalink)
        username = (og or {}).get("username")

        bd_item: Optional[Dict[str, Any]] = None
        if username and self.has_business_discovery:
            try:
                bd_item = await self._business_discovery_lookup(username, shortcode)
            except Exception as exc:
                logger.info(
                    "business_discovery lookup failed; falling back to OG meta",
                    extra={"username": username, "shortcode": shortcode, "error": str(exc)},
                )

        if bd_item:
            return IGPostInfo(
                permalink=permalink,
                shortcode=shortcode,
                author_name=username,
                author_url=f"https://www.instagram.com/{username}/" if username else None,
                title=bd_item.get("caption"),
                thumbnail_url=(og or {}).get("thumbnail_url"),
                media_type=_bd_media_type(bd_item) or _infer_media_type(permalink),
                like_count=bd_item.get("like_count"),
                comments_count=bd_item.get("comments_count"),
                timestamp=bd_item.get("timestamp"),
                source="business_discovery",
            )

        if og:
            return IGPostInfo(
                permalink=permalink,
                shortcode=shortcode,
                author_name=username,
                author_url=f"https://www.instagram.com/{username}/" if username else None,
                title=og.get("caption_preview"),
                thumbnail_url=og.get("thumbnail_url"),
                media_type=og.get("media_type") or _infer_media_type(permalink),
                like_count=og.get("like_count"),
                comments_count=og.get("comments_count"),
                source="og_meta",
            )

        return None

    async def _fetch_public_meta(self, permalink: str) -> Optional[Dict[str, Any]]:
        """Fetch the un-authed public IG page and parse its OG meta tags."""
        async def _do_request() -> httpx.Response:
            return await self._client.get(
                permalink,
                follow_redirects=True,
                headers={
                    "User-Agent": _PUBLIC_UA,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )

        try:
            response = await retry_async(_do_request, max_attempts=2, base_delay=0.5)
        except Exception as exc:
            logger.info(
                "Public IG page fetch failed",
                extra={"permalink": permalink, "error": str(exc)},
            )
            return None

        if response.status_code != 200 or not response.text:
            logger.info(
                "Public IG page returned non-200 / empty body",
                extra={"permalink": permalink, "status": response.status_code},
            )
            return None

        meta = _parse_public_meta(response.text)
        if not meta:
            logger.info(
                "Public IG page had no parseable OG meta",
                extra={"permalink": permalink},
            )
        return meta

    async def _business_discovery_lookup(
        self, username: str, shortcode: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Look up a public account's media via Business Discovery.

        Walks paginated media pages until the matching shortcode is found or
        ``_BD_MAX_PAGES`` pages have been scanned. Returns ``None`` if the
        target isn't a Business/Creator account or the shortcode isn't in the
        recent window.
        """
        if not self.has_business_discovery:
            return None

        media_fields = (
            "id,permalink,caption,media_type,timestamp,like_count,comments_count"
        )
        fields = (
            f"business_discovery.username({username})"
            f"{{username,media.limit(25){{{media_fields}}}}}"
        )
        url = f"{GRAPH_API_URL}/{self._ig_user_id}"
        params: Dict[str, str] = {"access_token": self._token, "fields": fields}

        for page_index in range(_BD_MAX_PAGES):
            response = await self._client.get(url, params=params)
            if response.status_code != 200:
                safe_url = str(response.request.url).split("?", 1)[0]
                logger.info(
                    "Business Discovery non-200",
                    extra={
                        "status": response.status_code,
                        "url": safe_url,
                        "body": response.text[:200],
                    },
                )
                return None

            payload = response.json() or {}
            bd = payload.get("business_discovery") or {}
            media = bd.get("media") or {}
            for item in media.get("data") or []:
                permalink = item.get("permalink") or ""
                if shortcode and f"/{shortcode}/" in permalink:
                    return item

            next_url = ((media.get("paging") or {}).get("next")) if media else None
            if not next_url:
                return None
            # Subsequent pages include the access_token in the next URL already.
            url, params = next_url, {}

        logger.info(
            "Business Discovery exhausted pages without matching shortcode",
            extra={"username": username, "shortcode": shortcode, "pages": _BD_MAX_PAGES},
        )
        return None
