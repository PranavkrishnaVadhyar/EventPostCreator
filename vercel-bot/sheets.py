"""
sheets.py — Google Sheets integration
======================================

Handles reading and writing event records to a Google Sheet via
the gspread library and a service-account credential file.

Environment variables (set in Vercel project settings):
  GOOGLE_SHEET_ID    — the spreadsheet ID from the Sheet URL
  GOOGLE_CREDS_JSON  — *contents* of the service-account JSON key
                       (paste the entire JSON string as the env var value;
                        this avoids having to upload a file to Vercel)
"""

import json
import logging
import os
from datetime import datetime

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

logger = logging.getLogger(__name__)

GOOGLE_SHEET_ID   = os.environ["GOOGLE_SHEET_ID"]
# On Vercel, store the full JSON content as an env var string.
# Locally, you can set GOOGLE_CREDS_JSON to a file path instead.
_CREDS_RAW        = os.getenv("GOOGLE_CREDS_JSON", "")

SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

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


def _build_credentials() -> Credentials:
    """
    Build Google credentials from either:
      a) A JSON string stored in the GOOGLE_CREDS_JSON env var  (Vercel)
      b) A file path stored in the GOOGLE_CREDS_FILE env var    (local dev)
    """
    creds_file = os.getenv("GOOGLE_CREDS_FILE")
    if creds_file and os.path.exists(creds_file):
        return Credentials.from_service_account_file(creds_file, scopes=SHEET_SCOPES)

    if _CREDS_RAW:
        info = json.loads(_CREDS_RAW)
        return Credentials.from_service_account_info(info, scopes=SHEET_SCOPES)

    raise EnvironmentError(
        "No Google credentials found. Set GOOGLE_CREDS_JSON (JSON string) "
        "or GOOGLE_CREDS_FILE (file path) in your environment."
    )


def _get_sheet() -> gspread.Worksheet:
    """Authenticate and return the first worksheet."""
    creds  = _build_credentials()
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID).sheet1


def _ensure_headers(sheet: gspread.Worksheet) -> None:
    """Write the header row if the sheet is brand new."""
    try:
        first_cell = sheet.cell(1, 1).value
    except Exception:
        first_cell = None

    if first_cell != "Timestamp":
        sheet.insert_row(SHEET_HEADERS, index=1)


def save_event_to_sheet(details: dict) -> bool:
    """
    Append one row of extracted event details (+ timestamp) to the sheet.
    Returns True on success, False on any failure.
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
        logger.info("Saved to sheet: %s", details.get("event_name"))
        return True

    except Exception as e:
        logger.error("save_event_to_sheet failed: %s", e)
        return False


def fetch_events_from_sheet() -> list[dict]:
    """
    Return all event rows (excluding the header) as a list of dicts.
    Returns an empty list on failure.
    """
    try:
        sheet   = _get_sheet()
        records = sheet.get_all_records()
        return records
    except Exception as e:
        logger.error("fetch_events_from_sheet failed: %s", e)
        return []
