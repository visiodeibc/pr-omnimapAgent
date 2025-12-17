"""
Onboarding messages and utilities for Telegram bot.

Contains all welcome messages, feature descriptions, and inline keyboard layouts
for user onboarding flow.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# =============================================================================
# Welcome Messages
# =============================================================================

WELCOME_MESSAGE = """🗺️ <b>Welcome to OmniMap Agent!</b>

I help you discover places and turn them into useful map links.

<b>🎯 What I can do:</b>

📍 <b>Place Search</b>
Send me any place name and I'll find it on Google Maps with ratings, reviews, and direct links.
<i>Example: "Blue Bottle Coffee Tokyo"</i>

💬 <b>Chat</b>
Ask me questions about places or just say hi! I remember our conversation for 30 minutes.

<b>🚀 Try it now:</b>
Send me a place name like "Eiffel Tower" to get started!"""

# Condensed welcome for users who message without using /start
CONDENSED_WELCOME = """👋 <b>Hi! I'm OmniMap.</b>

I help you find places and get Google Maps links.

<b>Try it:</b>
• Send a place name: "Central Park NYC"
• Ask me about any location!

Type /help for more info."""

# Help message with detailed feature documentation
HELP_MESSAGE = """📚 <b>OmniMap Agent - Help</b>

<b>Commands:</b>
/start - Show welcome message
/help - Show this help

<b>Features:</b>

<b>1. 📍 Place Search</b>
Simply type any place name and I'll search Google Maps.
• "Shibuya Crossing Tokyo"
• "Best coffee shop in Brooklyn"
• "Louvre Museum"

I'll return:
• Address and location
• Ratings and reviews
• Direct Google Maps link

<b>2. 💬 Conversation</b>
Ask me anything about places! I remember our conversation context for 30 minutes.

<b>Tips:</b>
• Be specific with locations for better results
• Include city/country for place searches
• I understand multiple languages!

<b>Coming soon:</b>
• Instagram Reels place extraction
• TikTok video place extraction

<b>Need help?</b> Just ask! 💡"""

# Feature-specific messages for quick action buttons
FEATURE_PLACE_SEARCH = """📍 <b>Place Search</b>

Send me any place name and I'll find it on Google Maps with details like:
• Address
• Ratings & reviews
• Direct Google Maps link

<b>Examples:</b>
• "Tokyo Tower"
• "Best ramen in Osaka"
• "Covent Garden London"

Try sending a place name now! 🔍"""


# =============================================================================
# Inline Keyboard Layouts
# =============================================================================

def get_welcome_keyboard() -> InlineKeyboardMarkup:
    """Get the inline keyboard for the welcome message."""
    keyboard = [
        [
            InlineKeyboardButton("📍 Try Place Search", callback_data="feature_place"),
            InlineKeyboardButton("❓ Help", callback_data="show_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_help_keyboard() -> InlineKeyboardMarkup:
    """Get the inline keyboard for the help message."""
    keyboard = [
        [
            InlineKeyboardButton("🏠 Back to Start", callback_data="show_start"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_feature_keyboard() -> InlineKeyboardMarkup:
    """Get the inline keyboard for feature detail messages."""
    keyboard = [
        [
            InlineKeyboardButton("🏠 Back to Start", callback_data="show_start"),
            InlineKeyboardButton("❓ Help", callback_data="show_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# =============================================================================
# Callback Data Handlers Map
# =============================================================================

CALLBACK_MESSAGES = {
    "feature_place": FEATURE_PLACE_SEARCH,
    "show_help": HELP_MESSAGE,
    "show_start": WELCOME_MESSAGE,
}


def get_callback_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    """Get the appropriate keyboard for a callback data type."""
    if callback_data == "show_help":
        return get_help_keyboard()
    elif callback_data == "show_start":
        return get_welcome_keyboard()
    else:
        return get_feature_keyboard()
