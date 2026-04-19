"""
api/webhook.py — Flask Webhook for Vercel
==========================================

Vercel calls this file on every POST Telegram sends to the webhook URL.
Flask handles routing cleanly:

  POST /api/webhook  →  receive Telegram update  →  dispatch()
  GET  /api/webhook  →  health check

Conversation state is persisted in /tmp/conv_state.json.
This works across warm Vercel invocations; cold starts reset it.
For multi-user production use, swap the _load/_save helpers for
an Upstash Redis call (see README).
"""

import json
import logging
import traceback

from flask import Flask, jsonify, request

from formatter import format_details_message, format_events_list
from pipeline import extract_details, generate_hook, generate_post
from sheets import fetch_events_from_sheet, save_event_to_sheet
from telegram_client import answer_callback_query, edit_message_text, send_message

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State store  (/tmp is writable on Vercel; persists within warm instances)
# ---------------------------------------------------------------------------

STATE_FILE = "/tmp/conv_state.json"


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def _get_user(chat_id: str) -> dict:
    return _load_state().get(chat_id, {})


def _set_user(chat_id: str, data: dict) -> None:
    state = _load_state()
    state[chat_id] = data
    _save_state(state)


def _clear_user(chat_id: str) -> None:
    state = _load_state()
    state.pop(chat_id, None)
    _save_state(state)


# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

MENU          = "MENU"
EVENT_TEXT    = "EVENT_TEXT"
STORIES       = "STORIES"
EXTRA_CONTEXT = "EXTRA_CONTEXT"

# ---------------------------------------------------------------------------
# Inline keyboard
# ---------------------------------------------------------------------------

MAIN_MENU_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "✍️ Create a new post", "callback_data": "new_post"}],
        [{"text": "📊 View past events",  "callback_data": "view_events"}],
    ]
}

# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------


@app.route("/api/webhook", methods=["GET"])
@app.route("/", methods=["GET"])
def health_check():
    """Simple liveness probe — lets you verify the deployment is up."""
    return "Event Post Creator webhook is live. ✅", 200


@app.route("/api/webhook", methods=["POST"])
def webhook():
    """
    Main entry point called by Telegram for every update.
    Must return HTTP 200 quickly; Telegram retries on non-200.
    """
    try:
        update = request.get_json(force=True, silent=True) or {}
        logger.info("Update received: %s", json.dumps(update)[:300])
        dispatch(update)
    except Exception:
        logger.error("Unhandled error:\n%s", traceback.format_exc())

    # Always 200 — even on internal errors, so Telegram doesn't retry
    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# Core dispatcher
# ---------------------------------------------------------------------------


def dispatch(update: dict) -> None:
    """Route an incoming Telegram update to the correct handler."""

    # ── Callback query (inline button tap) ──────────────────────────────────
    if "callback_query" in update:
        cq      = update["callback_query"]
        cq_id   = cq["id"]
        data    = cq.get("data", "")
        chat_id = str(cq["message"]["chat"]["id"])
        msg_id  = cq["message"]["message_id"]
        handle_callback(chat_id, msg_id, cq_id, data)
        return

    # ── Regular message ──────────────────────────────────────────────────────
    message = update.get("message")
    if not message:
        return

    chat_id = str(message["chat"]["id"])
    text    = message.get("text", "").strip()

    if not text:
        return

    # Commands — strip @BotName suffix if present
    if text.startswith("/"):
        handle_command(chat_id, text.split()[0].lower().split("@")[0])
        return

    # Plain text — route by current conversation state
    user  = _get_user(chat_id)
    state = user.get("state")

    if state == EVENT_TEXT:
        handle_event_text(chat_id, text, user)
    elif state == STORIES:
        handle_stories(chat_id, text, user)
    elif state == EXTRA_CONTEXT:
        handle_extra_context(chat_id, text, user)
    else:
        # No active conversation — show the welcome menu
        show_menu(chat_id)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def handle_command(chat_id: str, cmd: str) -> None:
    if cmd in ("/start", "/new"):
        _clear_user(chat_id)
        show_menu(chat_id)

    elif cmd == "/viewevents":
        send_message(chat_id, "⏳ Fetching your events from Google Sheets…")
        records = fetch_events_from_sheet()
        send_long_message(chat_id, format_events_list(records))

    elif cmd == "/skip":
        user = _get_user(chat_id)
        if user.get("state") == EXTRA_CONTEXT:
            user["extra_context"] = ""
            _set_user(chat_id, user)
            run_pipeline(chat_id, user)
        else:
            send_message(chat_id, "Nothing to skip right now. Use /new to start.")

    elif cmd == "/cancel":
        _clear_user(chat_id)
        send_message(chat_id, "❌ Cancelled. Send /new whenever you want to start again.")

    elif cmd == "/help":
        send_message(
            chat_id,
            "ℹ️ *Event Post Creator — Help*\n\n"
            "/new or /start — Show the welcome menu\n"
            "/viewevents    — List all past events from Google Sheets\n"
            "/skip          — Skip the optional extra-context step\n"
            "/cancel        — Cancel the current session\n"
            "/help          — Show this message",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


def show_menu(chat_id: str) -> None:
    _set_user(chat_id, {"state": MENU})
    send_message(
        chat_id,
        "🎤 *Event Post Creator* — LinkedIn Post Generator\n\nWhat would you like to do?",
        reply_markup=MAIN_MENU_KEYBOARD,
        parse_mode="Markdown",
    )


def handle_callback(chat_id: str, msg_id: int, cq_id: str, data: str) -> None:
    answer_callback_query(cq_id)

    if data == "view_events":
        edit_message_text(chat_id, msg_id, "⏳ Fetching your events from Google Sheets…")
        records = fetch_events_from_sheet()
        msg     = format_events_list(records)
        if len(msg) > 4096:
            edit_message_text(chat_id, msg_id, msg[:4096], parse_mode="Markdown")
            send_long_message(chat_id, msg[4096:])
        else:
            edit_message_text(chat_id, msg_id, msg, parse_mode="Markdown")
        send_message(chat_id, "Run /new to create a new post.")
        _clear_user(chat_id)

    elif data == "new_post":
        edit_message_text(
            chat_id, msg_id,
            "✍️ *Step 1/3 — Describe the event:*\n\n"
            "Include: event name, date, venue, topic, audience, your role, organiser, etc.\n\n"
            "Send your description when ready.",
            parse_mode="Markdown",
        )
        _set_user(chat_id, {"state": EVENT_TEXT})


# ---------------------------------------------------------------------------
# Post-creation conversation steps
# ---------------------------------------------------------------------------


def handle_event_text(chat_id: str, text: str, user: dict) -> None:
    user["event_text"] = text
    user["state"]      = STORIES
    _set_user(chat_id, user)
    send_message(
        chat_id,
        "✅ Got it!\n\n"
        "*Step 2/3 — Stories & memorable moments:*\n"
        "Share any highlights, audience reactions, or standout moments. "
        "These will be used to craft a compelling hook.\n\n"
        "Send your stories when ready.",
        parse_mode="Markdown",
    )


def handle_stories(chat_id: str, text: str, user: dict) -> None:
    user["stories"] = text
    user["state"]   = EXTRA_CONTEXT
    _set_user(chat_id, user)
    send_message(
        chat_id,
        "✅ Noted!\n\n"
        "*Step 3/3 — Extra context (optional):*\n"
        "Any specific tone, hashtags, or instructions for the post?\n\n"
        "Send your instructions, or type /skip to continue without extra context.",
        parse_mode="Markdown",
    )


def handle_extra_context(chat_id: str, text: str, user: dict) -> None:
    user["extra_context"] = text
    _set_user(chat_id, user)
    run_pipeline(chat_id, user)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(chat_id: str, user: dict) -> None:
    """
    Full pipeline: extract → save to sheet → show details → hook → post.
    Gemini calls are synchronous; Vercel Pro's 60-second timeout accommodates them.
    """
    event_text    = user.get("event_text", "")
    stories       = user.get("stories", "")
    extra_context = user.get("extra_context", "")

    # ── Step 1: Extract ──────────────────────────────────────────────────────
    send_message(chat_id, "🔍 *Step 1/3* — Extracting event details…", parse_mode="Markdown")
    try:
        details = extract_details(event_text)
    except Exception as e:
        logger.error("extract_details failed: %s", e)
        send_message(chat_id, "❌ Failed to extract event details. Check your input and try /new.")
        _clear_user(chat_id)
        return

    saved        = save_event_to_sheet(details)
    sheet_status = "✅ Saved to Google Sheets." if saved else "⚠️ Could not save to Google Sheets."

    send_long_message(
        chat_id,
        format_details_message(details) + f"\n\n{sheet_status}",
        parse_mode="Markdown",
    )

    # ── Step 2: Hook ─────────────────────────────────────────────────────────
    send_message(chat_id, "✨ *Step 2/3* — Generating hook…", parse_mode="Markdown")
    try:
        hook = generate_hook(details, stories)
    except Exception as e:
        logger.error("generate_hook failed: %s", e)
        send_message(chat_id, "❌ Failed to generate hook. Please try again with /new.")
        _clear_user(chat_id)
        return

    # ── Step 3: Post ─────────────────────────────────────────────────────────
    send_message(chat_id, "📝 *Step 3/3* — Generating full post…", parse_mode="Markdown")
    try:
        post = generate_post(hook, details, extra_context)
    except Exception as e:
        logger.error("generate_post failed: %s", e)
        send_message(chat_id, "❌ Failed to generate post. Please try again with /new.")
        _clear_user(chat_id)
        return

    # ── Deliver ───────────────────────────────────────────────────────────────
    send_message(chat_id, f"✨ *Generated Hook:*\n\n{hook}", parse_mode="Markdown")
    send_long_message(chat_id, "📝 *YOUR LINKEDIN POST:*\n\n" + post, parse_mode="Markdown")
    send_message(
        chat_id,
        "💡 Copy the post above and paste it directly into LinkedIn!\n\nRun /new to create another post.",
    )
    _clear_user(chat_id)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def send_long_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> None:
    """Split messages that exceed Telegram's 4096-character limit."""
    for i in range(0, len(text), 4096):
        send_message(chat_id, text[i : i + 4096], parse_mode=parse_mode)


# ---------------------------------------------------------------------------
# Local dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run locally:  python api/webhook.py
    # Expose with:  ngrok http 5000
    # Register:     python set_webhook.py set https://<ngrok-id>.ngrok.io/api/webhook
    app.run(host="0.0.0.0", port=5000, debug=True)
