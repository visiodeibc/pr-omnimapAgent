import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    from supabase_client import SupabaseRestClient

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    keyboard = [
        [InlineKeyboardButton("🎬 Reels → Maps", callback_data="reels_start")],
        [InlineKeyboardButton("🏓 Ping me!", callback_data="ping")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🗺️ OmniMap Agent\n\n"
        "Extract places from content and turn them into useful map links.\n\n"
        "Reels → Maps is under construction — tap to see status.",
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    await update.message.reply_text(
        "📚 Available commands:\n\n"
        "/start - Get started with the bot\n"
        "/help - Show this help message\n"
        "/hello - Trigger the Python worker hello-world demo"
    )


async def hello_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /hello command - demonstrates the job queue pipeline."""
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        await update.message.reply_text("⚠️ Unable to determine your Telegram account.")
        return

    # Get the Supabase client from context
    supabase_client: SupabaseRestClient = context.bot_data["supabase_client"]

    try:
        # Ensure session exists
        session = supabase_client.ensure_session(
            platform="telegram",
            platform_user_id=str(user.id),
            platform_chat_id=chat.id,
            metadata={
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "language_code": user.language_code,
            },
        )

        if not session:
            await update.message.reply_text(
                "❌ Could not create a session. Please try again later."
            )
            return

        # Append user message to session memory
        supabase_client.insert_session_memory(
            {
                "session_id": session["id"],
                "role": "user",
                "kind": "message",
                "content": {
                    "text": update.message.text or "",
                    "telegram_user_id": user.id,
                    "username": user.username,
                },
            }
        )

        # Create a job for the Python worker
        job = supabase_client.insert_job(
            {
                "type": "python_hello",
                "chat_id": chat.id,
                "payload": {
                    "session_id": session["id"],
                    "telegram_user_id": user.id,
                    "username": user.username,
                },
                "status": "queued",
                "session_id": session["id"],
            }
        )

        if not job:
            await update.message.reply_text(
                "❌ Failed to queue the Python agent. Try again later."
            )
            return

        await update.message.reply_text(
            "🤖 Hello request sent to Python worker. I will update you once it responds."
        )

    except Exception as exc:
        logger.exception("Error issuing hello command: %s", exc)
        await update.message.reply_text(
            "❌ Something went wrong talking to the Python worker."
        )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "ping":
        await query.answer("Pong! 🏓")
        await query.message.reply_text("🏓 Pong! The bot is working perfectly!")
    elif query.data == "reels_start":
        await query.answer("WIP")
        await query.message.reply_text(
            "🎬 Reels → Maps is a work in progress. I will update this soon!"
        )
    else:
        await query.answer("Unknown action")
