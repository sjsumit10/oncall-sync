"""Block Kit rendering.

Slack's own presentation layer, kept inside the Slack adapter so no vendor markup
leaks into the sync engine.
"""

from typing import Any

from app.domain.types import Announcement

#: Slack renders this in each reader's own timezone rather than ours, which is
#: the whole point for a shift that ends at 09:00 somewhere.
_DATE_FORMAT = "<!date^{epoch}^{{date_short_pretty}} at {{time}}|{fallback}>"


def local_time(epoch: int, fallback: str) -> str:
    return _DATE_FORMAT.format(epoch=epoch, fallback=fallback)


def build(announcement: Announcement) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": announcement.text}}
    ]

    context: list[str] = []
    if announcement.schedule_name:
        context.append(f"*{announcement.schedule_name}*")
    if announcement.handle:
        context.append(f"`@{announcement.handle}`")
    if announcement.shift_end is not None:
        epoch = int(announcement.shift_end.timestamp())
        fallback = announcement.shift_end.strftime("%a %d %b, %H:%M UTC")
        context.append(f"until {local_time(epoch, fallback)}")

    if context:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " · ".join(context)}],
            }
        )
    return blocks


def notification_text(announcement: Announcement) -> str:
    """The plain-text fallback.

    Also what shows in notifications and to screen readers, so it must stand on
    its own rather than saying "this message cannot be displayed".
    """
    return announcement.text
