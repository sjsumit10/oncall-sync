"""Slack OAuth v2 install flow.

Both a bot token and a user token are requested. Which one can actually write a
user group depends on the workspace's User Groups permission setting, not on our
app, so capturing both at install is what lets the write path degrade gracefully
instead of dead-ending on a workspace we cannot detect in advance.
"""

from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.http import ProviderAuthError, request
from app.domain.types import ChatInstall

AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
ACCESS_URL = "https://slack.com/api/oauth.v2.access"

BOT_SCOPES = (
    "usergroups:read",
    "usergroups:write",
    "channels:read",
    "groups:read",
    "chat:write",
    "users:read",
    "users:read.email",
    "team:read",
)
#: Requested so a workspace that restricts user-group management to admins can
#: still be served, using the installer's own authority.
USER_SCOPES = ("usergroups:write",)


def install_url(*, state: str, redirect_uri: str) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "client_id": settings.slack_client_id,
            "scope": ",".join(BOT_SCOPES),
            "user_scope": ",".join(USER_SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def complete_install(*, code: str, redirect_uri: str) -> ChatInstall:
    settings = get_settings()
    form = {
        "client_id": settings.slack_client_id,
        "client_secret": settings.slack_client_secret.get_secret_value(),
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        response = await request(client, "POST", ACCESS_URL, data=form)

    payload = response.json()
    if not payload.get("ok"):
        raise ProviderAuthError(f"Slack install failed: {payload.get('error', 'unknown_error')}")

    team = payload.get("team") or {}
    authed_user = payload.get("authed_user") or {}
    return ChatInstall(
        external_team_id=team.get("id", ""),
        team_name=team.get("name") or team.get("id", "Slack workspace"),
        bot_token=payload["access_token"],
        bot_user_id=payload.get("bot_user_id"),
        user_token=authed_user.get("access_token"),
        installing_user_external_id=authed_user.get("id"),
        scopes=payload.get("scope"),
        user_scopes=authed_user.get("scope"),
    )
