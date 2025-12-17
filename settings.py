import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from logging_config import get_environment


@dataclass(frozen=True)
class TelegramSettings:
    """Telegram-specific settings."""

    bot_token: str
    webhook_secret: str


@dataclass(frozen=True)
class InstagramSettings:
    """Instagram-specific settings."""

    access_token: str
    app_secret: Optional[str] = None
    account_id: Optional[str] = None


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
    if ig_access_token:
        instagram_settings = InstagramSettings(
            access_token=ig_access_token,
            app_secret=os.getenv("INSTAGRAM_APP_SECRET"),
            account_id=os.getenv("INSTAGRAM_ACCOUNT_ID"),
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

    # Load OpenAI settings (optional, enables agentic workflow)
    openai_settings = None
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        openai_settings = OpenAISettings(
            api_key=openai_api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
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
        google_places=google_places_settings,
    )


def clear_settings_cache() -> None:
    """Clear the settings cache (for testing)."""
    get_settings.cache_clear()
