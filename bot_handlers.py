from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from logging_config import get_logger
from onboarding import (
    CALLBACK_MESSAGES,
    CONDENSED_WELCOME,
    HELP_MESSAGE,
    WELCOME_MESSAGE,
    get_callback_keyboard,
    get_help_keyboard,
    get_welcome_keyboard,
)

if TYPE_CHECKING:
    from supabase_client import SupabaseRestClient

logger = get_logger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /start command with comprehensive onboarding.
    
    Shows welcome message with feature overview and interactive buttons.
    Also tracks that the user has seen onboarding in session metadata.
    """
    user = update.effective_user
    chat = update.effective_chat
    
    logger.info(
        "Start command received",
        extra={
            "user_id": user.id if user else None,
            "username": user.username if user else None,
            "chat_id": chat.id if chat else None,
        },
    )
    
    # Track onboarding in session metadata
    supabase_client: "SupabaseRestClient" = context.bot_data.get("supabase_client")
    if supabase_client and user and chat:
        try:
            import datetime as dt
            supabase_client.ensure_session(
                platform="telegram",
                platform_user_id=str(user.id),
                platform_chat_id=chat.id,
                metadata={
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "language_code": user.language_code,
                    "onboarding_shown_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning("Failed to track onboarding in session: %s", exc)
    
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="HTML",
        reply_markup=get_welcome_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /help command with detailed feature documentation.
    """
    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode="HTML",
        reply_markup=get_help_keyboard(),
    )


async def callback_query_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle inline keyboard button callbacks for onboarding navigation.
    
    Responds to button presses from welcome/help messages to show
    feature details or navigate back.
    """
    query = update.callback_query
    if not query:
        return
    
    await query.answer()  # Acknowledge the callback
    
    callback_data = query.data
    if not callback_data:
        return
    
    logger.debug(
        "Callback query received",
        extra={"callback_data": callback_data, "user_id": query.from_user.id},
    )
    
    # Get the message and keyboard for this callback
    message_text = CALLBACK_MESSAGES.get(callback_data)
    if not message_text:
        logger.warning("Unknown callback data: %s", callback_data)
        return
    
    keyboard = get_callback_keyboard(callback_data)
    
    # Edit the existing message with new content
    try:
        await query.edit_message_text(
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as exc:
        # Message might be unchanged, which raises an error
        logger.debug("Could not edit message: %s", exc)


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
