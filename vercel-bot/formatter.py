"""
formatter.py — Telegram message formatters
==========================================

Converts extracted event dicts and sheet records into
nicely formatted Markdown strings for Telegram messages.
"""


def format_details_message(details: dict) -> str:
    """Return a Markdown card summarising extracted event details."""
    takeaways = details.get("key_takeaways") or []
    takeaway_str = (
        "\n".join(f"  • {t}" for t in takeaways)
        if takeaways
        else "  _None listed_"
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


def format_events_list(records: list[dict]) -> str:
    """Return a numbered Markdown list of all past events from the sheet."""
    if not records:
        return "📭 No events logged yet."

    lines = [f"📊 *Past Events ({len(records)} total):*\n"]
    for i, r in enumerate(records, start=1):
        name      = r.get("event_name") or "Unnamed event"
        date      = r.get("date")       or "—"
        venue     = r.get("venue")      or "—"
        role      = r.get("my_role")    or "—"
        topic     = r.get("topic")      or "—"
        timestamp = r.get("Timestamp")  or "—"
        lines.append(
            f"*{i}. {name}*\n"
            f"   📅 {date}  |  📍 {venue}\n"
            f"   🎯 {topic}\n"
            f"   🎤 Role: {role}\n"
            f"   🕒 Logged: {timestamp}\n"
        )
    return "\n".join(lines)
