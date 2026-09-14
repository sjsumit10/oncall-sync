"""Adaptive Card rendering.

Teams' own presentation layer, kept inside the Teams adapter so no vendor
markup leaks into the sync engine — the same split as Slack's blocks.py.
"""

from typing import Any

from app.domain.types import Announcement

ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


def build(announcement: Announcement) -> dict[str, Any]:
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": announcement.text, "wrap": True}
    ]

    facts: list[dict[str, str]] = []
    if announcement.schedule_name:
        facts.append({"title": "Schedule", "value": announcement.schedule_name})
    if announcement.handle:
        facts.append({"title": "Handle", "value": f"@{announcement.handle}"})
    if announcement.shift_end is not None:
        facts.append(
            {"title": "Until", "value": announcement.shift_end.strftime("%a %d %b, %H:%M UTC")}
        )
    if facts:
        body.append({"type": "FactSet", "facts": facts})

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }


def notification_text(announcement: Announcement) -> str:
    """The plain-text fallback used alongside the card and for notifications."""
    return announcement.text
