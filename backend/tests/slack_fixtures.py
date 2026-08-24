"""Canned Slack Web API payloads."""

from typing import Any

API = "https://slack.com/api"


def ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def err(code: str, **fields: Any) -> dict[str, Any]:
    return {"ok": False, "error": code, **fields}


def install_response(
    *, with_user_token: bool = True, team_id: str = "T123", team_name: str = "Acme"
) -> dict[str, Any]:
    payload: dict[str, Any] = ok(
        access_token="xoxb-bot-token",
        token_type="bot",
        scope="usergroups:read,usergroups:write,chat:write,users:read.email",
        bot_user_id="B123",
        app_id="A123",
        team={"id": team_id, "name": team_name},
    )
    payload["authed_user"] = (
        {"id": "U_INSTALLER", "scope": "usergroups:write", "access_token": "xoxp-user-token"}
        if with_user_token
        else {"id": "U_INSTALLER"}
    )
    return payload


def usergroup(external_id: str, handle: str, name: str) -> dict[str, Any]:
    return {"id": external_id, "handle": handle, "name": name, "date_delete": 0}


def channel(external_id: str, name: str, *, is_member: bool = True, private: bool = False) -> dict:
    return {"id": external_id, "name": name, "is_member": is_member, "is_private": private}


def slack_user(external_id: str, name: str, email: str) -> dict[str, Any]:
    return {
        "id": external_id,
        "name": name,
        "real_name": name,
        "is_bot": False,
        "profile": {"display_name": name, "email": email},
    }
