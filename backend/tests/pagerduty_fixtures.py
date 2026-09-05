"""Canned PagerDuty API payloads, shaped like the real v2 responses."""

from typing import Any

API = "https://api.pagerduty.com"


def schedule(external_id: str, name: str, tz: str = "UTC") -> dict[str, Any]:
    return {
        "id": external_id,
        "type": "schedule",
        "summary": name,
        "name": name,
        "time_zone": tz,
        "description": f"{name} rotation",
        "html_url": f"https://acme.pagerduty.com/schedules/{external_id}",
    }


def schedules_page(items: list[dict[str, Any]], *, more: bool = False) -> dict[str, Any]:
    return {"schedules": items, "limit": 100, "offset": 0, "more": more, "total": len(items)}


def schedule_v3(external_id: str, name: str) -> dict[str, Any]:
    """A v3 schedule reference — the shift-based list endpoint returns only
    id/summary/urls, no time_zone or description."""
    return {
        "id": external_id,
        "type": "schedule_v3_reference",
        "summary": name,
        "self": f"{API}/v3/schedules/{external_id}",
        "html_url": f"https://acme.pagerduty.com/schedules/{external_id}",
    }


def oncall(
    user_id: str,
    name: str,
    email: str,
    start: str,
    end: str | None,
    level: int = 1,
    schedule_id: str = "PSCHED1",
) -> dict[str, Any]:
    """An /oncalls entry with include[]=users, which inflates the user reference."""
    return {
        "escalation_policy": {"id": "PEP1", "type": "escalation_policy_reference"},
        "escalation_level": level,
        "schedule": {"id": schedule_id, "type": "schedule_reference"},
        "user": {
            "id": user_id,
            "type": "user",
            "summary": name,
            "name": name,
            "email": email,
        },
        "start": start,
        "end": end,
    }


def oncalls_page(items: list[dict[str, Any]], *, more: bool = False) -> dict[str, Any]:
    return {"oncalls": items, "limit": 100, "offset": 0, "more": more}
