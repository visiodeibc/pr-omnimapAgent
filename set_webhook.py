#!/usr/bin/env python3
"""Script to set the Telegram webhook for the bot."""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from telegram import Bot

# Load .env file if present
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def set_webhook() -> None:
    """Set the Telegram webhook."""
    # Only load what we need for webhook setup
    bot_token = os.getenv("BOT_TOKEN")
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    public_url = os.getenv("PUBLIC_URL")

    if not bot_token:
        logger.error("BOT_TOKEN is required")
        sys.exit(1)

    if not webhook_secret:
        logger.error("WEBHOOK_SECRET is required")
        sys.exit(1)

    if not public_url:
        logger.error("PUBLIC_URL is required to set webhook")
        sys.exit(1)

    webhook_url = f"{public_url.rstrip('/')}/api/tg"

    bot = Bot(token=bot_token)

    try:
        # Delete existing webhook first
        logger.info("Deleting existing webhook...")
        await bot.delete_webhook(drop_pending_updates=True)

        # Set new webhook
        logger.info("Setting webhook to: %s", webhook_url)
        success = await bot.set_webhook(
            url=webhook_url,
            secret_token=webhook_secret,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )

        if success:
            logger.info("✅ Webhook set successfully!")

            # Get webhook info
            info = await bot.get_webhook_info()
            logger.info("Webhook info:")
            logger.info("  URL: %s", info.url)
            logger.info("  Has custom certificate: %s", info.has_custom_certificate)
            logger.info("  Pending update count: %s", info.pending_update_count)
            if info.last_error_date:
                logger.warning("  Last error date: %s", info.last_error_date)
                logger.warning("  Last error message: %s", info.last_error_message)
        else:
            logger.error("❌ Failed to set webhook")
            sys.exit(1)

    except Exception as exc:
        logger.exception("Error setting webhook: %s", exc)
        sys.exit(1)
    finally:
        # Cleanup
        await bot.shutdown()


def main() -> None:
    """Main entry point."""
    asyncio.run(set_webhook())


if __name__ == "__main__":
    main()
