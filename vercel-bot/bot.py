"""
bot.py — Telegram Bot for Event Post Creator
=============================================

New features in this version:
  - Google Sheets integration (gspread):
      * Saves extracted event details to a sheet after extraction.
      * /viewevents command fetches and displays all logged events from the sheet.
  - Extracted details are displayed to the user before post generation.
  - Conditional welcome menu: user chooses between creating a new post or
    viewing past events at the very start of every conversation.

Setup:
  pip install python-telegram-bot python-dotenv gspread google-auth

  .env keys required:
    TELEGRAM_BOT_TOKEN   — your bot token from @BotFather
    GOOGLE_SHEET_ID      — the spreadsheet ID from the Sheet URL
    GOOGLE_CREDS_JSON    — path to your service-account credentials JSON file
                           (default: credentials.json)
    HTTPS_PROXY          — optional SOCKS5/HTTP proxy for restricted networks

  Google Sheets service-account setup (one-time):
    1. Go to console.cloud.google.com → enable "Google Sheets API".
    2. Create a Service Account → download the JSON key.
    3. Share your Google Sheet with the service-account email (Editor role).
    4. Set GOOGLE_CREDS_JSON=path/to/key.json in .env (or drop it as
       credentials.json next to bot.py).
"""

import json
import logging
import os
from datetime import datetime

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest

from main import extract_details, generate_hook, generate_post

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
GOOGLE_SHEET_ID     = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON   = os.getenv("GOOGLE_CREDS_JSON", "credentials.json")

SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column order in the Google Sheet
SHEET_HEADERS = [
    "Timestamp",
    "event_name",
    "event_type",
    "date",
    "venue",
    "topic",
    "audience",
    "duration",
    "participant_count",
    "key_takeaways",
    "my_role",
    "organizer",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

# Welcome menu state
MENU = 0
# Post-creation flow states
EVENT_TEXT, STORIES, EXTRA_CONTEXT = range(1, 4)

# ---------------------------------------------------------------------------
# Google Sheets helpers
# ---------------------------------------------------------------------------


def _get_sheet() -> gspread.Worksheet:
    """Authenticate and return the first worksheet of the configured sheet."""
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_JSON, scopes=SHEET_SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    return spreadsheet.sheet1


def _ensure_headers(sheet: gspread.Worksheet) -> None:
    """Write header row if the sheet is empty."""
    if sheet.row_count == 0 or sheet.cell(1, 1).value != "Timestamp":
        sheet.insert_row(SHEET_HEADERS, index=1)


def save_event_to_sheet(details: dict) -> bool:
    """
    Append a new row with extracted event details + a timestamp.
    Returns True on success, False on failure.
    """
    try:
        sheet = _get_sheet()
        _ensure_headers(sheet)

        takeaways = details.get("key_takeaways") or []
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            details.get("event_name")        or "",
            details.get("event_type")        or "",
            details.get("date")              or "",
            details.get("venue")             or "",
            details.get("topic")             or "",
            details.get("audience")          or "",
            details.get("duration")          or "",
            details.get("participant_count") or "",
            "; ".join(takeaways) if isinstance(takeaways, list) else str(takeaways),
            details.get("my_role")           or "",
            details.get("organizer")         or "",
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info("Event saved to sheet: %s", details.get("event_name"))
        return True
    except Exception as e:
        logger.error("Failed to save event to sheet: %s", e)
        return False


def fetch_events_from_sheet() -> list[dict]:
    """
    Return all event rows (excluding the header) as a list of dicts.
    Returns an empty list on failure.
    """
    try:
        sheet = _get_sheet()
        records = sheet.get_all_records()  # uses first row as keys automatically
        return records
    except Exception as e:
        logger.error("Failed to fetch events from sheet: %s", e)
        return []


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_details_message(details: dict) -> str:
    """Return a nicely formatted Markdown summary of extracted event details."""
    takeaways = details.get("key_takeaways") or []
    takeaway_str = (
        "\n".join(f"  • {t}" for t in takeaways) if takeaways else "  _None listed_"
    )
    return (
        "📋 *Extracted Event Details:*\n\n"
        f"🏷 *Event Name:* {details.get('event_name') or '—'}\n"
        f"📌 *Type:* {details.get('event_type') or '—'}\n"
        f"📅 *Date:* {details.get('date') or '—'}\n"
        f"📍 *Venue:* {details.get('venue') or '—'}\n"
        f"🎯 *Topic:* {details.get('topic') or '—'}\n"
        f"👥 *Audience:* {details.get('audience') or '—'}\n"
        f"⏱ *Duration:* {details.get('duration') or '—'}\n"
        f"🔢 *Participants:* {details.get('participant_count') or '—'}\n"
        f"🎤 *My Role:* {details.get('my_role') or '—'}\n"
        f"🏫 *Organizer:* {details.get('organizer') or '—'}\n\n"
        f"💡 *Key Takeaways:*\n{takeaway_str}"
    )


def _format_events_list(records: list[dict]) -> str:
    """Return a Markdown string listing all past events from the sheet."""
    if not records:
        return "📭 No events logged yet."

    lines = [f"📊 *Past Events ({len(records)} total):*\n"]
    for i, r in enumerate(records, start=1):
        name      = r.get("event_name")  or "Unnamed event"
        date      = r.get("date")        or "—"
        venue     = r.get("venue")       or "—"
        role      = r.get("my_role")     or "—"
        topic     = r.get("topic")       or "—"
        timestamp = r.get("Timestamp")   or "—"
        lines.append(
            f"*{i}. {name}*\n"
            f"   📅 {date}  |  📍 {venue}\n"
            f"   🎯 {topic}\n"
            f"   🎤 Role: {role}\n"
            f"   🕒 Logged: {timestamp}\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Welcome menu
# ---------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show welcome menu with two choices."""
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("✍️ Create a new post", callback_data="new_post")],
        [InlineKeyboardButton("📊 View past events",  callback_data="view_events")],
    ]
    await update.message.reply_text(
        "🎤 *Event Post Creator* — LinkedIn Post Generator\n\n"
        "What would you like to do?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return MENU


async def menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the welcome-menu button press."""
    query = update.callback_query
    await query.answer()

    if query.data == "view_events":
        await query.edit_message_text("⏳ Fetching your events from Google Sheets…")
        records = fetch_events_from_sheet()
        msg = _format_events_list(records)

        # Telegram message limit guard
        if len(msg) > 4096:
            chunks = [msg[i : i + 4096] for i in range(0, len(msg), 4096)]
            await query.edit_message_text(chunks[0], parse_mode="Markdown")
            for chunk in chunks[1:]:
                await context.bot.send_message(query.message.chat_id, chunk, parse_mode="Markdown")
        else:
            await query.edit_message_text(msg, parse_mode="Markdown")

        await context.bot.send_message(
            query.message.chat_id,
            "Run /new to create a new post.",
        )
        return ConversationHandler.END

    # new_post branch — proceed to event description step
    await query.edit_message_text(
        "✍️ *Step 1/3 — Describe the event:*\n\n"
        "Include: event name, date, venue, topic, audience, your role, organiser, etc.\n\n"
        "Send your description when ready.",
        parse_mode="Markdown",
    )
    return EVENT_TEXT


# ---------------------------------------------------------------------------
# Post-creation flow
# ---------------------------------------------------------------------------


async def receive_event_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store event description, ask for stories."""
    context.user_data["event_text"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Got it!\n\n"
        "*Step 2/3 — Stories & memorable moments:*\n"
        "Share any highlights, audience reactions, or standout moments. "
        "These will be used to craft a compelling hook.\n\n"
        "Send your stories when ready.",
        parse_mode="Markdown",
    )
    return STORIES


async def receive_stories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store stories, ask for optional extra context."""
    context.user_data["stories"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Noted!\n\n"
        "*Step 3/3 — Extra context (optional):*\n"
        "Any specific tone, hashtags, or instructions for the post?\n\n"
        "Send your instructions, or type /skip to continue without extra context.",
        parse_mode="Markdown",
    )
    return EXTRA_CONTEXT


async def receive_extra_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store extra context and run the full pipeline."""
    context.user_data["extra_context"] = update.message.text.strip()
    return await _run_pipeline(update, context)


async def skip_extra_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User skipped extra context — run pipeline with empty string."""
    context.user_data["extra_context"] = ""
    return await _run_pipeline(update, context)


async def _run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Full pipeline:
      1. Extract event details  → save to sheet  → display to user
      2. Generate hook
      3. Generate full post     → display to user
    """
    event_text   = context.user_data["event_text"]
    stories      = context.user_data["stories"]
    extra_context = context.user_data.get("extra_context", "")

    # ── Step 1: Extract details ──────────────────────────────────────────────
    await update.message.reply_text(
        "🔍 *Step 1/3* — Extracting event details…", parse_mode="Markdown"
    )
    try:
        details = extract_details(event_text)
    except Exception as e:
        logger.error("extract_details failed: %s", e)
        await update.message.reply_text(
            "❌ Failed to extract event details. Check your input and try /new."
        )
        return ConversationHandler.END

    # Save to Google Sheets
    saved = save_event_to_sheet(details)
    sheet_status = "✅ Saved to Google Sheets." if saved else "⚠️ Could not save to Google Sheets."

    # Display extracted details to the user BEFORE generating the post
    details_msg = _format_details_message(details)
    await update.message.reply_text(
        details_msg + f"\n\n{sheet_status}",
        parse_mode="Markdown",
    )

    # ── Step 2: Generate hook ────────────────────────────────────────────────
    await update.message.reply_text(
        "✨ *Step 2/3* — Generating hook…", parse_mode="Markdown"
    )
    try:
        hook = generate_hook(details, stories)
    except Exception as e:
        logger.error("generate_hook failed: %s", e)
        await update.message.reply_text(
            "❌ Failed to generate hook. Please try again with /new."
        )
        return ConversationHandler.END

    # ── Step 3: Generate post ────────────────────────────────────────────────
    await update.message.reply_text(
        "📝 *Step 3/3* — Generating full post…", parse_mode="Markdown"
    )
    try:
        post = generate_post(hook, details, extra_context)
    except Exception as e:
        logger.error("generate_post failed: %s", e)
        await update.message.reply_text(
            "❌ Failed to generate post. Please try again with /new."
        )
        return ConversationHandler.END

    # ── Send hook ────────────────────────────────────────────────────────────
    await update.message.reply_text(
        f"✨ *Generated Hook:*\n\n{hook}", parse_mode="Markdown"
    )

    # ── Send full post (split if > 4096 chars) ───────────────────────────────
    header       = "📝 *YOUR LINKEDIN POST:*\n\n"
    full_message = header + post

    if len(full_message) <= 4096:
        await update.message.reply_text(full_message, parse_mode="Markdown")
    else:
        await update.message.reply_text(header, parse_mode="Markdown")
        for i in range(0, len(post), 4096):
            await update.message.reply_text(post[i : i + 4096])

    await update.message.reply_text(
        "💡 Copy the post above and paste it directly into LinkedIn!\n\n"
        "Run /new to create another post."
    )

    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Utility handlers
# ---------------------------------------------------------------------------


async def view_events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/viewevents — fetch and display all logged events outside the conv flow."""
    await update.message.reply_text("⏳ Fetching your events from Google Sheets…")
    records = fetch_events_from_sheet()
    msg = _format_events_list(records)

    if len(msg) > 4096:
        for i in range(0, len(msg), 4096):
            await update.message.reply_text(msg[i : i + 4096], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Cancelled. Send /new whenever you want to start again."
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message."""
    await update.message.reply_text(
        "ℹ️ *Event Post Creator — Help*\n\n"
        "/new or /start — Show the welcome menu\n"
        "/viewevents    — List all past events from Google Sheets\n"
        "/skip          — Skip the optional extra-context step\n"
        "/cancel        — Cancel the current session\n"
        "/help          — Show this message",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------


def main() -> None:
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
        proxy=proxy_url,
    )

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("new",   start),
        ],
        states={
            MENU: [
                CallbackQueryHandler(menu_choice, pattern="^(new_post|view_events)$"),
            ],
            EVENT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_event_text),
            ],
            STORIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_stories),
            ],
            EXTRA_CONTEXT: [
                CommandHandler("skip", skip_extra_context),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_extra_context),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("viewevents", view_events_command))
    app.add_handler(CommandHandler("help",       help_command))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
