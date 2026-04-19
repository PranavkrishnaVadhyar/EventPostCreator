"""
telegram_client.py — Synchronous Telegram Bot API client
=========================================================

Thin wrapper around the Telegram Bot API using the `requests` library.
We use synchronous HTTP because Vercel's Python runtime executes the
handler synchronously (BaseHTTPRequestHandler). No asyncio needed.
"""

import json
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _post(method: str, payload: dict) -> dict:
    """Make a POST request to the Telegram Bot API."""
    url = f"{BASE_URL}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Telegram API error [%s]: %s", method, e)
        return {}


def send_message(
    chat_id: str,
    text: str,
    parse_mode: str = None,
    reply_markup: dict = None,
) -> dict:
    """Send a text message to a chat."""
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _post("sendMessage", payload)


def edit_message_text(
    chat_id: str,
    message_id: int,
    text: str,
    parse_mode: str = None,
) -> dict:
    """Edit an existing message (used for inline-keyboard updates)."""
    payload = {
        "chat_id":    chat_id,
        "message_id": message_id,
        "text":       text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _post("editMessageText", payload)


def answer_callback_query(callback_query_id: str, text: str = "") -> dict:
    """Acknowledge an inline button press (removes the loading spinner)."""
    return _post("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text":              text,
    })


def set_webhook(webhook_url: str) -> dict:
    """Register the webhook URL with Telegram. Call once after deploying."""
    return _post("setWebhook", {"url": webhook_url})


def delete_webhook() -> dict:
    """Remove the current webhook (switch back to polling mode)."""
    return _post("deleteWebhook", {})


def get_webhook_info() -> dict:
    """Return current webhook configuration from Telegram."""
    url = f"{BASE_URL}/getWebhookInfo"
    try:
        return requests.get(url, timeout=10).json()
    except Exception as e:
        logger.error("getWebhookInfo error: %s", e)
        return {}
