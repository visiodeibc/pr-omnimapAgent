import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional

from logging_config import get_environment


@dataclass(frozen=True)
class TelegramSettings:
    """Telegram-specific settings."""

    bot_token: str
    webhook_secret: str


@dataclass(frozen=True)
class InstagramSettings:
    """Instagram-specific settings."""

    access_token: Optional[str] = None
    app_secret: Optional[str] = None
    account_id: Optional[str] = None
    verify_token: Optional[str] = None
    access_token_map: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class FacebookSettings:
    """Facebook app settings for OAuth and Graph API usage."""

    app_id: str
    app_secret: str
    redirect_uri: str
    login_scopes: str
    graph_api_version: str
    allowed_return_urls: tuple[str, ...]


@dataclass(frozen=True)
class TikTokSettings:
    """TikTok-specific settings."""

    client_key: str
    client_secret: str
    access_token: Optional[str] = None


@dataclass(frozen=True)
class GooglePlacesSettings:
    """Google Places API settings for place search."""

    api_key: str


@dataclass(frozen=True)
class OpenAISettings:
    """OpenAI API settings for agentic workflow."""

    api_key: str
    model: str = "gpt-4o-mini"  # Cost-efficient default
    timeout: float = 30.0  # Request timeout in seconds
    max_retries: int = 2  # Number of retries for transient failures


@dataclass(frozen=True)
class Settings:
    """Application settings with multi-platform support."""

    # Core settings
    supabase_url: str
    supabase_key: str
    poll_interval: float
    enable_worker: bool
    public_url: Optional[str]

    # Environment
    environment: str = "local"  # local, staging, production

    # OpenAI settings for agentic workflow
    openai: Optional[OpenAISettings] = None

    # Platform-specific settings (optional per platform)
    telegram: Optional[TelegramSettings] = None
    instagram: Optional[InstagramSettings] = None
    tiktok: Optional[TikTokSettings] = None
    facebook: Optional[FacebookSettings] = None

    # External API settings
    google_places: Optional[GooglePlacesSettings] = None

    @property
    def enabled_platforms(self) -> list[str]:
        """List of configured platforms."""
        platforms = []
        if self.telegram:
            platforms.append("telegram")
        if self.instagram:
            platforms.append("instagram")
        if self.tiktok:
            platforms.append("tiktok")
        return platforms

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment in ("production", "prod")

    @property
    def agent_enabled(self) -> bool:
        """Check if agentic workflow is enabled (requires OpenAI)."""
        return self.openai is not None

    @property
    def google_places_enabled(self) -> bool:
        """Check if Google Places API is configured."""
        return self.google_places is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from environment variables."""
    url = os.getenv("SUPABASE_URL")
    if not url:
        raise RuntimeError("SUPABASE_URL is required for the Python agent")

    key = os.getenv("SUPABASE_SERVICE_ROLE")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE must be set")

    try:
        interval = float(os.getenv("PYTHON_WORKER_POLL_INTERVAL", "5"))
    except ValueError as exc:
        raise RuntimeError("PYTHON_WORKER_POLL_INTERVAL must be numeric") from exc

    enable_worker = os.getenv("PYTHON_WORKER_ENABLED", "true").lower() not in {"0", "false", "no"}
    public_url = os.getenv("PUBLIC_URL")
    environment = get_environment()

    # Load Telegram settings (required for now, optional in future)
    telegram_settings = None
    bot_token = os.getenv("BOT_TOKEN")
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    if bot_token and webhook_secret:
        telegram_settings = TelegramSettings(
            bot_token=bot_token,
            webhook_secret=webhook_secret,
        )
    elif bot_token or webhook_secret:
        # Partial config is an error
        raise RuntimeError("Both BOT_TOKEN and WEBHOOK_SECRET are required for Telegram")

    # At least one platform must be configured
    if not telegram_settings:
        raise RuntimeError("At least one messaging platform must be configured (BOT_TOKEN required)")

    # Load Instagram settings (optional)
    instagram_settings = None
    ig_access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    ig_access_token_map_raw = os.getenv("INSTAGRAM_ACCESS_TOKEN_MAP")
    access_token_map: Optional[Dict[str, str]] = None
    if ig_access_token_map_raw:
        try:
            parsed_map = json.loads(ig_access_token_map_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "INSTAGRAM_ACCESS_TOKEN_MAP must be valid JSON (object mapping account_id -> token)"
            ) from exc
        if not isinstance(parsed_map, dict) or not parsed_map:
            raise RuntimeError(
                "INSTAGRAM_ACCESS_TOKEN_MAP must be a non-empty JSON object mapping account_id -> token"
            )
        normalized_map: Dict[str, str] = {}
        for acct_id, token in parsed_map.items():
            if not acct_id or not token:
                continue
            normalized_map[str(acct_id)] = str(token)
        if not normalized_map:
            raise RuntimeError(
                "INSTAGRAM_ACCESS_TOKEN_MAP must contain at least one account_id -> token entry"
            )
        access_token_map = normalized_map

    if ig_access_token or access_token_map:
        instagram_settings = InstagramSettings(
            access_token=ig_access_token,
            app_secret=os.getenv("INSTAGRAM_APP_SECRET"),
            account_id=os.getenv("INSTAGRAM_ACCOUNT_ID"),
            verify_token=os.getenv("INSTAGRAM_VERIFY_TOKEN"),
            access_token_map=access_token_map,
        )

    # Load TikTok settings (optional)
    tiktok_settings = None
    tiktok_client_key = os.getenv("TIKTOK_CLIENT_KEY")
    tiktok_client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    if tiktok_client_key and tiktok_client_secret:
        tiktok_settings = TikTokSettings(
            client_key=tiktok_client_key,
            client_secret=tiktok_client_secret,
            access_token=os.getenv("TIKTOK_ACCESS_TOKEN"),
        )

    # Load Facebook app settings (optional, enables OAuth helper endpoints)
    facebook_settings = None
    facebook_app_id = os.getenv("FACEBOOK_APP_ID")
    facebook_app_secret = os.getenv("FACEBOOK_APP_SECRET")
    facebook_redirect_uri = os.getenv("FACEBOOK_REDIRECT_URI")
    facebook_scopes = os.getenv(
        "FACEBOOK_LOGIN_SCOPES",
        "pages_show_list,pages_read_engagement,pages_manage_metadata,"
        "instagram_business_basic,instagram_business_manage_messages",
    )
    facebook_graph_version = os.getenv("FACEBOOK_GRAPH_API_VERSION", "v24.0")
    facebook_allowed_return_urls = tuple(
        value.strip()
        for value in os.getenv("FACEBOOK_ALLOWED_RETURN_URLS", "").split(",")
        if value.strip()
    )

    if facebook_app_id or facebook_app_secret or facebook_redirect_uri:
        if not facebook_app_id or not facebook_app_secret:
            raise RuntimeError(
                "FACEBOOK_APP_ID and FACEBOOK_APP_SECRET are required for Facebook OAuth"
            )

        if not facebook_redirect_uri:
            if not public_url:
                raise RuntimeError(
                    "FACEBOOK_REDIRECT_URI or PUBLIC_URL must be set for Facebook OAuth"
                )
            facebook_redirect_uri = f"{public_url.rstrip('/')}/auth/facebook/callback"

        facebook_settings = FacebookSettings(
            app_id=facebook_app_id,
            app_secret=facebook_app_secret,
            redirect_uri=facebook_redirect_uri,
            login_scopes=facebook_scopes,
            graph_api_version=facebook_graph_version,
            allowed_return_urls=facebook_allowed_return_urls,
        )

    # Load OpenAI settings (optional, enables agentic workflow)
    openai_settings = None
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        try:
            openai_timeout = float(os.getenv("OPENAI_TIMEOUT", "30.0"))
        except ValueError:
            openai_timeout = 30.0

        try:
            openai_max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
        except ValueError:
            openai_max_retries = 2

        openai_settings = OpenAISettings(
            api_key=openai_api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            timeout=openai_timeout,
            max_retries=openai_max_retries,
        )

    # Load Google Places settings (optional, enables place search)
    google_places_settings = None
    google_places_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if google_places_api_key:
        google_places_settings = GooglePlacesSettings(
            api_key=google_places_api_key,
        )

    return Settings(
        supabase_url=url,
        supabase_key=key,
        poll_interval=max(1.0, interval),
        enable_worker=enable_worker,
        public_url=public_url,
        environment=environment,
        openai=openai_settings,
        telegram=telegram_settings,
        instagram=instagram_settings,
        tiktok=tiktok_settings,
        facebook=facebook_settings,
        google_places=google_places_settings,
    )


def clear_settings_cache() -> None:
    """Clear the settings cache (for testing)."""
    get_settings.cache_clear()
